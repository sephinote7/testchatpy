"""
ML/통계 라우터: 주간 키워드, 추천, 월간 인기.
app.py에서 include_router로 포함하고, lifespan에서 load_ml_data()를 호출해야 합니다.
mlFunctionVersion은 load_ml_data() 내부에서만 import (konlpy/Okt가 JVM 필요 → Render 등에서 상단 import 시 기동 실패 방지).
"""
import logging
import os
from io import BytesIO

import numpy as np
from PIL import Image
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List
from wordcloud import WordCloud

logger = logging.getLogger(__name__)

STOPWORDS = set([
    "하다", "있다", "되다", "것", "수", "되", "오늘",
    "입니다", "합니다", "한", "으로", "을", "를", "의",
    "가", "에", "도", "며", "및", "과", "와", "로", "에서", "중"
])

# 라우터 (prefix 없이 등록 시 /recommend, /weekly-keywords 등 그대로 노출)
router = APIRouter(tags=["ML"])

# 모듈 레벨 상태 (load_ml_data()로 채워짐)
like_row = None
bbs_row = None
cmt_like_row = None
comment_row = None
bbs = None
tfidf_vectorizer = None
tfidf_mat = None
top_keywords = None
weekly_wordcloud_image = None


def load_ml_data():
    """앱 시작 시 한 번 호출. DB에서 bbs 등 로드 후 TF-IDF·주간 키워드·워드클라우드 생성. JVM(konlpy) 없으면 스킵."""
    global like_row, bbs_row, cmt_like_row, comment_row
    global bbs, tfidf_vectorizer, tfidf_mat
    global top_keywords, weekly_wordcloud_image

    try:
        from mlFunctionVersion import (
            get_db_connection,
            load_table_as_df,
            prepare_bbs_tfidf,
        )
    except Exception as e:
        logger.warning("ML 데이터 로딩 스킵 (예: JVM/konlpy 미설치): %s", e)
        return

    try:
        conn = get_db_connection()
        like_row = load_table_as_df(conn, "bbs_like")
        bbs_row = load_table_as_df(conn, "bbs")
        cmt_like_row = load_table_as_df(conn, "cmt_like")
        comment_row = load_table_as_df(conn, "bbs_comment")

        bbs, tfidf_vectorizer, tfidf_mat = prepare_bbs_tfidf(bbs_row)

        one_week_ago = pd.Timestamp.now() - pd.Timedelta(days=7)
        bbs_week = bbs[bbs["created_at"] >= one_week_ago].copy()

        if not bbs_week.empty:
            tfidf_week = tfidf_vectorizer.transform(bbs_week["embedding"])
            keyword_scores = np.array(tfidf_week.sum(axis=0)).flatten()
            keywords = tfidf_vectorizer.get_feature_names_out()
            filtered_indices = [i for i, word in enumerate(keywords) if word not in STOPWORDS]
            filtered_scores = keyword_scores[filtered_indices]
            filtered_keywords = keywords[filtered_indices]
            top_indices = filtered_scores.argsort()[::-1][:10]
            top_keywords = [
                {"keyword": filtered_keywords[i], "score": float(filtered_scores[i])}
                for i in top_indices
            ]
        else:
            top_keywords = []

        if top_keywords:
            keyword_dict = {item["keyword"]: item["score"] for item in top_keywords}
            # 한글 표시: 프로젝트 fonts/ 우선 → Windows(맑은고딕) → Linux(Debian fonts-nanum) 순. 없으면 글자가 네모(□)로 나옴.
            _dir = os.path.dirname(os.path.abspath(__file__))
            font_path = None
            for path in (
                os.path.join(_dir, "fonts", "NanumGothic.ttf"),
                os.path.join(_dir, "fonts", "NanumBarunGothic.ttf"),
                "C:/Windows/Fonts/malgun.ttf",
                "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
            ):
                if os.path.isfile(path):
                    font_path = path
                    break
            try:
                if font_path:
                    wc = WordCloud(
                        font_path=font_path,
                        width=800,
                        height=400,
                        background_color="white",
                    ).generate_from_frequencies(keyword_dict)
                else:
                    raise FileNotFoundError("no korean font")
            except Exception:
                wc = WordCloud(width=800, height=400, background_color="white").generate_from_frequencies(keyword_dict)
            img_io = BytesIO()
            wc.to_image().save(img_io, format="PNG")
            img_io.seek(0)
            weekly_wordcloud_image = img_io
        else:
            weekly_wordcloud_image = None

        if "similarity" not in bbs.columns:
            bbs["similarity"] = 0.0

        logger.info("ML 데이터 로딩 완료")
    except Exception as e:
        logger.warning("ML 데이터 로딩 실패(ML 라우트만 비동작): %s", e)
        top_keywords = []
        weekly_wordcloud_image = None


# --- Pydantic 모델 ---
class RecommendationRequest(BaseModel):
    user_id: str


class PostResponse(BaseModel):
    bbs_id: int
    title: str
    content: str
    similarity: float
    likeCnt: int


class RecommendationResponse(BaseModel):
    user_id: str
    recommendations: List[PostResponse]


# --- 엔드포인트 ---
@router.post("/recommend", response_model=RecommendationResponse)
async def recommend_posts(request: RecommendationRequest):
    # ML 미로딩/사용자 활동 없음 시 503/404 대신 200 + 빈 목록 → 프론트에서 "등록된 인기글이 없습니다"로 통일
    if bbs is None:
        return RecommendationResponse(user_id=request.user_id, recommendations=[])
    from mlFunctionVersion import (
        compute_user_activity,
        compute_user_vector,
        generate_recommendations,
    )

    final_result = compute_user_activity(
        request.user_id, like_row, bbs_row, cmt_like_row, comment_row
    )
    if final_result.empty:
        return RecommendationResponse(user_id=request.user_id, recommendations=[])

    user_vector = compute_user_vector(final_result, bbs, tfidf_mat)
    if np.linalg.norm(user_vector) == 0:
        return RecommendationResponse(user_id=request.user_id, recommendations=[])

    recommendations = generate_recommendations(
        user_vector, bbs, tfidf_mat, final_result, like_row
    )
    recommendations = recommendations.merge(
        bbs_row[["bbs_id", "title", "content"]],
        on="bbs_id",
        how="left",
        suffixes=("", "_new"),
    )
    if "title" not in recommendations.columns and "title_new" in recommendations.columns:
        recommendations["title"] = recommendations["title_new"]
    if "content" not in recommendations.columns and "content_new" in recommendations.columns:
        recommendations["content"] = recommendations["content_new"]

    result_list = [
        PostResponse(
            bbs_id=int(row["bbs_id"]),
            title=row.get("title", ""),
            content=row.get("content", ""),
            similarity=float(row["similarity"]),
            likeCnt=int(row.get("likeCnt", 0)),
        )
        for _, row in recommendations.iterrows()
    ]
    return RecommendationResponse(user_id=request.user_id, recommendations=result_list)


@router.get("/monthly-top")
async def monthly_top():
    if bbs is None:
        return {"count": 0, "posts": []}
    from mlFunctionVersion import generate_monthly_top

    monthly = generate_monthly_top(bbs_row, bbs, like_row)
    if "title_x" in monthly.columns:
        monthly["title"] = monthly["title_x"]
    if "content_x" in monthly.columns:
        monthly["content"] = monthly["content_x"]
    monthly = monthly.rename(columns={"bbs_id": "bbsId"})
    return {
        "count": len(monthly),
        "posts": monthly[["bbsId", "title", "content", "final_score", "likeCnt"]].to_dict(orient="records"),
    }


@router.get("/weekly-keywords")
async def weekly_keywords():
    if top_keywords is None:
        return {"count": 0, "keywords": []}
    return {"count": len(top_keywords), "keywords": top_keywords}


def _placeholder_wordcloud_png():
    """워드클라우드 미준비 시 200 응답용 placeholder PNG (404 방지, OpaqueResponseBlocking 완화)."""
    img = Image.new("RGB", (800, 400), color=(248, 250, 252))
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


@router.get("/weekly-wordcloud")
async def weekly_wordcloud():
    if weekly_wordcloud_image is None:
        # 404 대신 placeholder 반환 → img 태그가 실패하지 않아 OpaqueResponseBlocking/NS_BINDING_ABORTED 완화
        body = _placeholder_wordcloud_png()
        return StreamingResponse(
            body,
            media_type="image/png",
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    weekly_wordcloud_image.seek(0)
    return StreamingResponse(
        weekly_wordcloud_image,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )

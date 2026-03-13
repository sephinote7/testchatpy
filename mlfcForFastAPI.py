from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from wordcloud import WordCloud
from io import BytesIO
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from contextlib import asynccontextmanager
import logging
import numpy as np
import pandas as pd
import uvicorn

STOPWORDS = set([
    "하다", "있다", "되다", "것", "수", "되", "오늘",
    "입니다", "합니다", "한", "으로", "을", "를", "의",
    "가", "에", "도", "며", "및", "과", "와", "로", "에서", "중"
])

# =========================
# 🔽 기존 추천 로직 import (수정 없음)
# =========================
from mlFunctionVersion import (
    get_db_connection,
    load_table_as_df,
    compute_user_activity,
    prepare_bbs_tfidf,
    compute_user_vector,
    generate_recommendations,
    generate_monthly_top
)

# =========================
# 로깅 설정
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# 전역 변수
# =========================
like_row = None
bbs_row = None
cmt_like_row = None
comment_row = None
bbs = None
tfidf_vectorizer = None
tfidf_mat = None
top_keywords = None
weekly_wordcloud_image = None  

# =========================
# Lifespan 이벤트 (앱 시작 시 1회 실행)
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global like_row, bbs_row, cmt_like_row, comment_row
    global bbs, tfidf_vectorizer, tfidf_mat

    logger.info("데이터 로딩 시작...")

    conn = get_db_connection()
    like_row = load_table_as_df(conn, "bbs_like")
    bbs_row = load_table_as_df(conn, "bbs")
    cmt_like_row = load_table_as_df(conn, "cmt_like")
    comment_row = load_table_as_df(conn, "bbs_comment")

    bbs, tfidf_vectorizer, tfidf_mat = prepare_bbs_tfidf(bbs_row)

    # =========================
    # 이번 주 키워드 추출
    # =========================
    global top_keywords

    one_week_ago = pd.Timestamp.now() - pd.Timedelta(days=7)
    bbs_week = bbs[bbs['created_at'] >= one_week_ago].copy()

    if not bbs_week.empty:
        tfidf_week = tfidf_vectorizer.transform(bbs_week['embedding'])
        keyword_scores = np.array(tfidf_week.sum(axis=0)).flatten()
        keywords = tfidf_vectorizer.get_feature_names_out()

        filtered_indices = [i for i, word in enumerate(keywords) if word not in STOPWORDS]
        filtered_scores = keyword_scores[filtered_indices]
        filtered_keywords = keywords[filtered_indices]

        top_indices = filtered_scores.argsort()[::-1][:10]
        top_keywords = [
            {
                "keyword": filtered_keywords[i],
                "score": float(filtered_scores[i])
            }
            for i in top_indices
        ]
    else:
        top_keywords = []

    global weekly_wordcloud_image

    if top_keywords and len(top_keywords) > 0:
        keyword_dict = {
            item["keyword"]: item["score"]
            for item in top_keywords
        }

        font_path = "C:/Windows/Fonts/malgun.ttf"

        wc = WordCloud(
            font_path=font_path,
            width=800,
            height=400,
            background_color="white"
        ).generate_from_frequencies(keyword_dict)

        img_io = BytesIO()
        wc.to_image().save(img_io, format="PNG")
        img_io.seek(0)

        weekly_wordcloud_image = img_io
    else:
        weekly_wordcloud_image = None

    if "similarity" not in bbs.columns:
      bbs["similarity"] = 0.0

    logger.info("데이터 로딩 완료")

    yield

    logger.info("애플리케이션 종료")


# =========================
# FastAPI 앱 생성
# =========================
app = FastAPI(
    title="게시글 추천 API",
    version="1.0.0",
    lifespan=lifespan
)

# =========================
# Pydantic 모델 정의
# =========================
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


# =========================
# 루트 엔드포인트
# =========================
@app.get("/")
async def root():
    return {
        "message": "게시글 추천 API",
        "endpoints": {
            "POST /recommend": "유저 기반 추천",
            "GET /monthly-top": "월간 인기글"
        }
    }


# =========================
# 추천 API
# =========================
@app.post("/recommend", response_model=RecommendationResponse)
async def recommend_posts(request: RecommendationRequest):

    if bbs is None:
        raise HTTPException(status_code=503, detail="데이터가 아직 로딩되지 않았습니다.")

    final_result = compute_user_activity(
        request.user_id,
        like_row,
        bbs_row,
        cmt_like_row,
        comment_row
    )

    if final_result.empty:
        raise HTTPException(status_code=404, detail="사용자 활동 데이터가 없습니다.")

    user_vector = compute_user_vector(final_result, bbs, tfidf_mat)

    if np.linalg.norm(user_vector) == 0:
        raise HTTPException(status_code=400, detail="유저 벡터 생성 실패")

    # 1️⃣ 추천 먼저 생성
    recommendations = generate_recommendations(
        user_vector,
        bbs,
        tfidf_mat,
        final_result,
        like_row
    )

    # 2️⃣ 충돌 방지 suffix 사용
    recommendations = recommendations.merge(
        bbs_row[["bbs_id", "title", "content"]],
        on="bbs_id",
        how="left",
        suffixes=("", "_new")
    )

    # 3️⃣ 만약 title이 없으면 title_new 사용
    if "title" not in recommendations.columns and "title_new" in recommendations.columns:
        recommendations["title"] = recommendations["title_new"]

    if "content" not in recommendations.columns and "content_new" in recommendations.columns:
        recommendations["content"] = recommendations["content_new"]

    result_list = []
    for _, row in recommendations.iterrows():
        result_list.append(
            PostResponse(
                bbs_id=int(row["bbs_id"]),
                title=row.get("title", ""),
                content=row.get("content", ""),
                similarity=float(row["similarity"]),
                likeCnt=int(row.get("likeCnt", 0))
            )
        )

    return RecommendationResponse(
        user_id=request.user_id,
        recommendations=result_list
    )


# =========================
# 월간 인기글 API
# =========================
@app.get("/monthly-top")
async def monthly_top():

    if bbs is None:
        raise HTTPException(status_code=503, detail="데이터가 아직 로딩되지 않았습니다.")

    monthly = generate_monthly_top(bbs_row, bbs, like_row)
    print('mmmmmmmmmmmmmmmmmmmmm', monthly.columns)

    # 🔽 title/content 정리 (중복 컬럼 대응)
    if "title_x" in monthly.columns:
        monthly["title"] = monthly["title_x"]

    if "content_x" in monthly.columns:
        monthly["content"] = monthly["content_x"]

    # bbs_id -> bbsId
    monthly = monthly.rename(columns={ "bbs_id": "bbsId"})
    
    return {
        "count": len(monthly),
        "posts": monthly[
            ["bbsId", "title", "content", "final_score", "likeCnt"]
        ].to_dict(orient="records")
    }

# =========================
# 이번 주 인기 키워드 API
# =========================
@app.get("/weekly-keywords")
async def weekly_keywords():

    if top_keywords is None:
        raise HTTPException(status_code=503, detail="데이터가 아직 로딩되지 않았습니다.")

    return {
        "count": len(top_keywords),
        "keywords": top_keywords
    }

# =========================
# 이번 주 워드클라우드 이미지 API
# =========================
@app.get("/weekly-wordcloud")
async def weekly_wordcloud():

    if weekly_wordcloud_image is None:
        raise HTTPException(status_code=404, detail="워드클라우드가 없습니다.")

    weekly_wordcloud_image.seek(0)

    return StreamingResponse(
        weekly_wordcloud_image,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"}
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # 프론트 주소
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# 실행
# =========================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
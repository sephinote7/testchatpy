# 라우터 아님. app.py의 ml_routes.py 및 mlfcForFastAPI.py에서 import하여 사용.
from ast import literal_eval
import warnings
import numpy as np
import os
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from konlpy.tag import Okt
from urllib.parse import urlparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# =========================
# 초기 설정
# =========================
STOPWORDS = set([
    "하다", "있다", "되다", "것", "수", "되", "오늘",
    "입니다", "합니다", "한", "으로", "을", "를", "의",
    "가", "에", "도", "며", "및", "과", "와", "로", "에서"
])

okt = Okt()
WEIGHTS = {
    'likeCnt': 2.0,
    'dislikeCnt': -1.5,
    'commentCnt': 4.0,
    'cmtLikeCnt': 0.5,
    'cmtDislikeCnt': -0.5
}
ALPHA = 0.7
BETA = 0.3

# =========================
# 유틸 함수
# =========================
def korean_tokenizer(text):
    # tokens = [word for word, pos in okt.pos(text) if pos in ["Noun","Verb","Adjective"]]
    tokens = [word for word, pos in okt.pos(text) if pos in ["Noun","Adjective"]]
    return [t for t in tokens if t not in STOPWORDS]

def get_db_connection():
    """Render: DATABASE_URL 우선 사용. 없으면 user/password/host/port/dbname 사용."""
    load_dotenv()
    raw_url = os.getenv("DATABASE_URL")
    url = (raw_url.strip() if raw_url else None) or None
    try:
        if url and "@" in url:
            return psycopg2.connect(dsn=url)
        user = os.getenv("user")
        password = os.getenv("password")
        host = os.getenv("host")
        port = os.getenv("port")
        dbname = os.getenv("dbname")
        if not all([user, password, host, port, dbname]):
            raise Exception(
                "ML DB 연결: Render 환경변수에 DATABASE_URL 또는 user/password/host/port/dbname 을 설정하세요. "
                "DATABASE_URL 사용 시 형식: postgresql://USER:PASSWORD@HOST:PORT/DBNAME (비밀번호와 호스트 사이에 @ 필수)"
            )
        return psycopg2.connect(
            user=user,
            password=password,
            host=host,
            port=str(port).strip(),
            dbname=dbname,
        )
    except Exception as e:
        raise Exception(f"DB 연결 실패: {e}")

def load_table_as_df(connection, table_name):
    query = f"SELECT * FROM {table_name}"
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*SQLAlchemy connectable.*", category=UserWarning)
        return pd.read_sql(query, connection)

# =========================
# 유저 활동 데이터 처리
# =========================
def compute_user_activity(target_user, like_row, bbs_row, cmt_like_row, comment_row):
    # 댓글 작성 집계
    user_comments = comment_row[comment_row['member_id'] == target_user]
    user_cmt_stats = user_comments.groupby('bbs_id').size().reset_index(name='commentCnt')

    # 게시글 좋아요/싫어요 집계
    user_likes = like_row[(like_row['member_id'] == target_user) & (like_row['is_like'] == True)]
    user_dislikes = like_row[(like_row['member_id'] == target_user) & (like_row['is_like'] == False)]
    user_like_stats = user_likes[['bbs_id']].assign(likeCnt=1)
    user_dislike_stats = user_dislikes[['bbs_id']].assign(dislikeCnt=1)

    # 댓글 좋아요/싫어요 집계
    user_cmt_likes = pd.merge(
        cmt_like_row[cmt_like_row['member_id'] == target_user], 
        comment_row[['cmt_id', 'bbs_id']], on='cmt_id'
    )
    user_cmt_like_stats = user_cmt_likes[user_cmt_likes['is_like'] == True].groupby('bbs_id').size().reset_index(name='cmtLikeCnt')
    user_cmt_dislike_stats = user_cmt_likes[user_cmt_likes['is_like'] == False].groupby('bbs_id').size().reset_index(name='cmtDislikeCnt')

    # 활동한 게시글 ID
    active_bbs_ids = pd.concat([
        user_cmt_stats['bbs_id'], 
        user_like_stats['bbs_id'], 
        user_dislike_stats['bbs_id'],
        user_cmt_like_stats['bbs_id']
    ]).unique()

    user_activity_df = pd.DataFrame({'bbs_id': active_bbs_ids})
    for df in [user_cmt_stats, user_like_stats, user_dislike_stats, user_cmt_like_stats, user_cmt_dislike_stats]:
        user_activity_df = pd.merge(user_activity_df, df, on='bbs_id', how='left')

    # 게시글 기본 정보 결합 (작성글 제외, created_at 포함)
    final_result = pd.merge(
        user_activity_df,
        bbs_row.loc[
            (bbs_row['member_id'] != target_user) & (bbs_row['bbs_div'] != 'NOTI'),
            ['bbs_id', 'created_at']
        ],
        on='bbs_id',
        how='inner'
    )

    # NaN 처리
    cols_to_fill = ['commentCnt', 'likeCnt', 'dislikeCnt', 'cmtLikeCnt', 'cmtDislikeCnt']
    final_result[cols_to_fill] = final_result[cols_to_fill].fillna(0).astype(int)

    # 점수 계산
    final_result['score'] = (
        final_result['likeCnt']       * WEIGHTS['likeCnt']
      + final_result['dislikeCnt']    * WEIGHTS['dislikeCnt']
      + final_result['commentCnt']    * WEIGHTS['commentCnt']
      + final_result['cmtLikeCnt']    * WEIGHTS['cmtLikeCnt']
      + final_result['cmtDislikeCnt'] * WEIGHTS['cmtDislikeCnt']
    )
    final_result = final_result[final_result['score'] > 0]
    final_result['score_norm'] = np.log1p(final_result['score'])

    # created_at 안전하게 datetime 변환
    final_result['created_at'] = pd.to_datetime(final_result['created_at'], errors='coerce')

    current_time = pd.Timestamp.now()
    final_result['days_diff'] = (current_time - final_result['created_at']).dt.days
    final_result['days_diff'] = final_result['days_diff'].fillna(0)
    final_result.loc[final_result['days_diff'] < 0, 'days_diff'] = 0
    final_result['recency_weight'] = 1 / (1 + final_result['days_diff'])
    final_result['score'] = final_result['score'] * final_result['recency_weight']
    final_result = final_result[final_result['score'] > 0]
    final_result['score_norm'] = np.log1p(final_result['score'])

    return final_result

# =========================
# 게시글 전처리 및 TF-IDF
# =========================
def prepare_bbs_tfidf(bbs_row):
    bbs_filtered = bbs_row[
        (bbs_row['bbs_id'].notnull()) &
        (bbs_row['bbs_div'] != 'NOTI') &
        (bbs_row['del_yn'] == 'N') &
        (bbs_row['created_at'] >= (pd.Timestamp.now() - pd.Timedelta(days=180)))
    ].copy()
    bbs_filtered['title'] = bbs_filtered['title'].fillna("")
    bbs_filtered['content'] = bbs_filtered['content'].fillna("")
    bbs_filtered['embedding'] = (
        (bbs_filtered['title'] + " ") * 1 + 
        (bbs_filtered['content'] + " ") * 3
    )

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*token_pattern.*", category=UserWarning)
        tfidf_vectorizer = TfidfVectorizer(
            max_features=2000,
            min_df=2,
            ngram_range=(1, 2),
            tokenizer=korean_tokenizer
        )
        tfidf_mat = tfidf_vectorizer.fit_transform(bbs_filtered['embedding'])
    return bbs_filtered, tfidf_vectorizer, tfidf_mat

# =========================
# 유저 벡터 계산
# =========================
def compute_user_vector(final_result, bbs, tfidf_mat):
    user_vector = np.zeros(tfidf_mat.shape[1])

    # bbs_id -> tfidf_mat row mapping 생성
    bbs_id_to_idx = {bbs_id: i for i, bbs_id in enumerate(bbs['bbs_id'])}

    for _, row in final_result.iterrows():
        bbs_id = row['bbs_id']
        weight = row['score_norm']
        
        if bbs_id not in bbs_id_to_idx:
            # TF-IDF 행렬에 없는 게시글이면 건너뜀
            continue

        idx = bbs_id_to_idx[bbs_id]
        post_vector = tfidf_mat[idx].toarray().flatten()
        user_vector += weight * post_vector

    user_vector = np.nan_to_num(user_vector)
    norm = np.linalg.norm(user_vector)
    if norm > 0:
        user_vector = user_vector / norm
    return user_vector

# =========================
# 추천 생성
# =========================
def generate_recommendations(user_vector, bbs, tfidf_mat, final_result, like_row=None):
    similarity = cosine_similarity(user_vector.reshape(1, -1), tfidf_mat)[0]
    bbs['similarity'] = similarity
    bbs_filtered = bbs[~bbs['bbs_id'].isin(final_result['bbs_id'])]

    recommendations = bbs_filtered.sort_values('similarity', ascending=False).head(10)

    # =========================
    # 좋아요 수 추가
    # =========================
    if like_row is not None:
        like_counts = like_row[like_row['is_like'] == True].groupby('bbs_id').size().reset_index(name='likeCnt')
        recommendations = pd.merge(recommendations, like_counts, on='bbs_id', how='left')
        recommendations['likeCnt'] = recommendations['likeCnt'].fillna(0).astype(int)

    return recommendations

# =========================
# 월간 TOP 게시글 추천 (좋아요 포함)
# =========================
def generate_monthly_top(bbs_row, bbs, like_row=None):
    monthly_candidates = bbs_row[
        (bbs_row['created_at'] >= (pd.Timestamp.now() - pd.Timedelta(days=30)))
    ].copy()

    # 중복 제거 및 집계
    if {'views','like_count','comment_count'}.issubset(monthly_candidates.columns):
        monthly_candidates = monthly_candidates.groupby('bbs_id', as_index=False).agg({
        'views': 'sum',
        'like_count': 'sum',
        'comment_count': 'sum'
    })


    # 기본 인기 점수
    if {'views','like_count','comment_count'}.issubset(monthly_candidates.columns):
        monthly_candidates['popularity_score'] = (
            monthly_candidates['views']*0.5 +
            monthly_candidates['like_count']*2 +
            monthly_candidates['comment_count']*1.5
        )
    else:
        monthly_candidates['popularity_score'] = 1.0

    monthly_candidates = monthly_candidates.merge(
        bbs[['bbs_id', 'similarity']], on='bbs_id', how='left'
    )
    monthly_candidates['similarity'] = monthly_candidates['similarity'].fillna(0.0)

    # =========================
    # 좋아요 수 추가
    # =========================
    if like_row is not None:
        like_counts = like_row[like_row['is_like'] == True].groupby('bbs_id').size().reset_index(name='likeCnt')
        monthly_candidates = pd.merge(monthly_candidates, like_counts, on='bbs_id', how='left')
        monthly_candidates['likeCnt'] = monthly_candidates['likeCnt'].fillna(0).astype(int)

    monthly_candidates['final_score'] = (
        ALPHA * monthly_candidates['popularity_score'] +
        BETA * monthly_candidates['similarity']
    )
    monthly_top_posts = monthly_candidates.sort_values('final_score', ascending=False).head(10)
    return monthly_top_posts

# =========================
# 메인 함수
# =========================
def main(target_user='user1@test.com'):
    connection = get_db_connection()
    like_row = load_table_as_df(connection, "bbs_like")
    bbs_row = load_table_as_df(connection, "bbs")
    cmt_like_row = load_table_as_df(connection, "cmt_like")
    comment_row = load_table_as_df(connection, "bbs_comment")

    # ======================
    # 기존 로직 유지
    # ======================
    final_result = compute_user_activity(target_user, like_row, bbs_row, cmt_like_row, comment_row)
    bbs, tfidf_vectorizer, tfidf_mat = prepare_bbs_tfidf(bbs_row)
    user_vector = compute_user_vector(final_result, bbs, tfidf_mat)

    print("user_vector NaN:", np.isnan(user_vector).any())
    print("user_vector norm:", np.linalg.norm(user_vector))

    recommendations = generate_recommendations(user_vector, bbs, tfidf_mat, final_result, like_row)
    print(recommendations)

    monthly_top_posts = generate_monthly_top(bbs_row, bbs, like_row)
    print("\n", monthly_top_posts)

    # ======================
    # 이번 주 키워드 추출 (추가, 후처리)
    # ======================
    one_week_ago = pd.Timestamp.now() - pd.Timedelta(days=7)
    bbs_week = bbs[bbs['created_at'] >= one_week_ago].copy()
    if not bbs_week.empty:
        tfidf_week = tfidf_vectorizer.transform(bbs_week['embedding'])
        keyword_scores = np.array(tfidf_week.sum(axis=0)).flatten()
        keywords = tfidf_vectorizer.get_feature_names_out()
        # STOPWORDS 기반 필터링
        filtered_indices = [i for i, word in enumerate(keywords) if word not in STOPWORDS]
        filtered_scores = keyword_scores[filtered_indices]
        filtered_keywords = keywords[filtered_indices]
        top_indices = filtered_scores.argsort()[::-1][:10]
        top_keywords = [(filtered_keywords[i], float(filtered_scores[i])) for i in top_indices]
        print("\n이번 주 인기 키워드:")
        for word, score in top_keywords:
            print(f"{word}: {score:.3f}")
    else:
        print("\n이번 주 게시글이 없습니다.")

if __name__ == "__main__":
    main()
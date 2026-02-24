-- bot_msg: AI 상담 메시지 저장 (cnsl_id + member_id 당 1행)
-- msg_data: jsonb, content 배열에 { speaker, text, type, timestamp } 누적
-- summary: 요약 텍스트 (상담 종료 후 등)
CREATE TABLE IF NOT EXISTS bot_msg (
  bot_msg_id   SERIAL PRIMARY KEY,
  cnsl_id      INT NOT NULL,
  member_id    VARCHAR(255) NOT NULL,
  msg_data     JSONB NOT NULL DEFAULT '{"content":[]}',
  summary      TEXT,
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(cnsl_id, member_id)
);

CREATE INDEX IF NOT EXISTS idx_bot_msg_cnsl_member ON bot_msg(cnsl_id, member_id);

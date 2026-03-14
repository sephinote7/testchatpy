-- ai_msg에 (cnsl_id, member_id) UNIQUE 제약 추가
-- ON CONFLICT (cnsl_id, member_id) 사용을 위해 필요.
--
-- 실행 전 중복 확인 (Supabase SQL Editor):
--   SELECT cnsl_id, member_id, COUNT(*) FROM ai_msg GROUP BY cnsl_id, member_id HAVING COUNT(*) > 1;
-- 중복이 있으면 한 행만 남기고 정리한 뒤 아래 블록 실행.
--
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.ai_msg'::regclass
      AND conname = 'ai_msg_cnsl_member_key'
      AND contype = 'u'
  ) THEN
    ALTER TABLE public.ai_msg
      ADD CONSTRAINT ai_msg_cnsl_member_key UNIQUE (cnsl_id, member_id);
  END IF;
END $$;

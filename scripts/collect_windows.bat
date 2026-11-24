@echo off
REM 프로모션 허브 - 내 PC에서 수집해 Supabase로 올리기 (GitHub Actions가 해외 IP로 차단될 때 대안)
REM 1) 아래 PROMOHUB_INGEST_TOKEN 값에 받은 수집 토큰을 붙여넣으세요.
REM 2) 최초 1회:  pip install -r requirements.txt  &&  python -m playwright install chromium
REM 3) 작업 스케줄러에 이 파일을 3시간 간격으로 등록하면 자동 수집됩니다.
cd /d %~dp0..
set SUPABASE_URL=https://wjfbcbiyzoymqqnoemvu.supabase.co
set SUPABASE_ANON_KEY=sb_publishable_-DNHcg_lvpePh3aeXGRXGw_qDJAkXI5
set PROMOHUB_INGEST_TOKEN=여기에_수집토큰_붙여넣기
python -m promohub.cli collect --sink supabase %*

# Microsoft 공식 Playwright Python 이미지 사용
# Chromium 및 모든 시스템 의존성이 포함되어 있어 별도 playwright install 불필요
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# playwright-stealth가 pkg_resources(setuptools)를 사용하므로 먼저 설치
RUN pip install --no-cache-dir setuptools

# 나머지 의존성 레이어를 소스 코드와 분리하여 빌드 캐시 최적화
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 소스 복사
COPY src/ ./src/

# 스크린샷 저장 디렉토리 생성
RUN mkdir -p /app/screenshots && chmod 777 /app/screenshots

# 로그가 버퍼 없이 즉시 출력되도록 설정 (docker logs에서 실시간 확인 가능)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "src.main"]

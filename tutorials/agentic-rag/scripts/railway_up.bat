@echo off
REM ##########################################################################
REM Deploy Agentic RAG to Railway
REM Prerequisites:
REM - Railway CLI installed: https://docs.railway.com/reference/cli-api
REM - Logged in: railway login
REM - OPENAI_API_KEY environment variable set
REM ##########################################################################

setlocal

echo ========================================
echo Starting Railway deployment...
echo ========================================
echo.

if "%OPENAI_API_KEY%"=="" (
    echo Error: OPENAI_API_KEY environment variable is not set.
    echo Please set it before running this script.
    pause
    exit /b 1
)

echo ========================================
echo Initializing Railway project...
echo ========================================
cmd /c railway init -n "agentic-rag-os"
echo.

echo ========================================
echo Deploying PgVector database...
echo ========================================
cmd /c railway deploy -t 3jJFCA
echo.

echo ========================================
echo Waiting 15 seconds for database to be ready...
echo ========================================
timeout /t 15 /nobreak >nul
echo.

echo ========================================
echo Creating application service with environment variables...
echo ========================================
cmd /c railway add --service agentic-rag-os ^
  --variables "DB_DRIVER=postgresql+psycopg" ^
  --variables "DB_USER=${{pgvector.PGUSER}}" ^
  --variables "DB_PASS=${{pgvector.PGPASSWORD}}" ^
  --variables "DB_HOST=${{pgvector.PGHOST}}" ^
  --variables "DB_PORT=${{pgvector.PGPORT}}" ^
  --variables "DB_DATABASE=${{pgvector.PGDATABASE}}" ^
  --variables "OPENAI_API_KEY=%OPENAI_API_KEY%"
echo.

echo ========================================
echo Deploying application...
echo ========================================
cmd /c railway up --service agentic-rag-os -d
echo.

echo ========================================
echo Creating public domain...
echo ========================================
cmd /c railway domain --service agentic-rag-os
echo.

echo ========================================
echo Deployment complete!
echo ========================================
echo.
echo Useful commands:
echo   railway logs --service agentic-rag-os  - View application logs
echo   railway status              - Check deployment status
echo   railway open                - Open project in browser
echo   railway variables           - View environment variables
echo.

pause
endlocal

FROM agnohq/python:3.12

ARG USER=app
ARG APP_DIR=/app
ENV APP_DIR=${APP_DIR}
ENV PYTHONPATH=${APP_DIR}

# Create user and home directory
RUN groupadd -g 61000 ${USER} \
  && useradd -g 61000 -u 61000 -ms /bin/bash -d ${APP_DIR} ${USER}

WORKDIR ${APP_DIR}

# Copy requirements.txt
COPY requirements.txt ./

# Install requirements
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Set permissions for the /app directory
RUN chown -R ${USER}:${USER} ${APP_DIR}

# Switch to non-root user
USER ${USER}

# Expose port
EXPOSE 8080

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

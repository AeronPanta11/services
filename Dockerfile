FROM python:3.10

# Create user first
RUN useradd -m -u 1000 user

# Switch to non-root user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

# Add TensorFlow environment variables to reduce logging noise
WORKDIR /app

COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=user . /app

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]

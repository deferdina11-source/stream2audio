FROM python:3.12-slim

# Install ffmpeg, curl, unzip
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl unzip && \
    rm -rf /var/lib/apt/lists/*

# Install Deno system-wide (required by yt-dlp 2026+ for YouTube)
RUN curl -fsSL https://dl.deno.land/release/latest/deno-x86_64-unknown-linux-gnu.zip -o /tmp/deno.zip && \
    unzip /tmp/deno.zip -d /usr/local/bin/ && \
    chmod +x /usr/local/bin/deno && \
    rm /tmp/deno.zip

# Verify deno is available
RUN deno --version

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Verify yt-dlp can find deno
RUN python -c "import shutil; print('deno at:', shutil.which('deno'))"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]

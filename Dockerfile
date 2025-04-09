FROM python:3.8

WORKDIR /app

# non free repos
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gnupg2 \
    software-properties-common \
    && apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 0x5a16e7281be7a449 \
    && add-apt-repository "deb http://deb.debian.org/debian buster main contrib non-free" \
    && add-apt-repository "deb http://deb.debian.org/debian buster-updates main contrib non-free" \
    && apt-get update

# ffmpeg (core) with non-free codecs
RUN apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# video libs
RUN apt-get -y update && \
    apt-get install -y --no-install-recommends \
    libwebm-dev \
    libxvidcore4 \
    libvorbis-dev \
    libopus-dev \
    && rm -rf /var/lib/apt/lists/*

# audio libs
RUN apt-get -y update && \
    apt-get install -y --no-install-recommends \
    libvorbis-dev \
    libopus-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY app.py app.py
COPY templates templates

CMD ["python", "app.py"]
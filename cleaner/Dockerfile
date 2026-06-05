FROM catcord-bots-framework:latest

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN mkdir -p /app/cleaner && touch /app/cleaner/__init__.py
COPY main.py /app/cleaner/main.py
COPY event_main.py /app/cleaner/event_main.py
COPY cleaner.py /app/cleaner/cleaner.py
COPY messages.py /app/cleaner/messages.py
COPY message_parts.json /app/cleaner/message_parts.json

ENTRYPOINT ["python", "-u", "-m", "cleaner.event_main"]

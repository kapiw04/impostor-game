# Impostor

FastAPI + Redis backend for a simple "secret word" game.

 ## Roadmap

* [x] Room lifecycle: create/join/leave, lobby state, start/end game, handle disconnect/reconnect.
* [ ] Roles + secret word: pick 1 impostor, pick a secret word from a category, distribute word to non-impostors, send “you are impostor” to impostor.
* [ ] Rounds + turn order: timed speaking turns, track who already spoke, round transitions.
* [ ] Voting: start vote phase, collect votes, handle ties/revote.
* [ ] Win conditions: impostor guessed the word / impostor eliminated; end screen + summary.
* [ ] Word packs: categories, difficulty, custom word lists per room, profanity filter if needed.
* [ ] UX events over WS: server-authoritative state snapshots + incremental events, client resync on reconnect.


## Run it
Requires Python 3.12 and Redis.

```bash
export REDIS_URL=<your_redis_url>
uv run fastapi dev impostor/main.py --host 0.0.0.0 --port 8000 
```

Or with Docker:

```bash
docker compose up --build
```

## Tests
Uses testcontainers to spin up Redis.

```bash
uv run pytest
```

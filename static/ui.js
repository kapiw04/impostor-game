import { $ } from "./dom.js";
import { state } from "./state.js";

let roleFlashTimer = null;
const TIME_BAR_WIDTH = 12;

function formatTags(tags) {
  if (!tags.length) {
    return "";
  }
  return tags.map((tag) => `[${tag}]`).join(" ");
}

function formatTimeBar(label, remaining, total) {
  if (!Number.isFinite(remaining) || !Number.isFinite(total) || total <= 0) {
    return "";
  }
  const safeRemaining = Math.max(0, Math.floor(remaining));
  const ratio = Math.max(0, Math.min(1, safeRemaining / total));
  const filled = Math.round(ratio * TIME_BAR_WIDTH);
  const bar = "#".repeat(filled) + "-".repeat(TIME_BAR_WIDTH - filled);
  return `${label} [${bar}] ${safeRemaining}s`;
}

export function setStatus(message) {
  $("status").textContent = message;
}

export function setScreen(name) {
  state.screen = name;
  $("screen-setup").hidden = name !== "setup";
  $("screen-nick").hidden = name !== "nick";
  $("screen-lobby").hidden = name !== "lobby";
  $("screen-game").hidden = name !== "game";
  $("screen-voting").hidden = name !== "voting";
  $("screen-end").hidden = name !== "end";

  const showRoleUi = name === "game" || name === "voting";
  const banner = $("role-banner");
  const aimBtn = $("aim-btn");
  const flash = $("role-flash");
  const aimModal = $("aim-modal");
  if (!showRoleUi) {
    banner.hidden = true;
    aimBtn.hidden = true;
    flash.hidden = true;
    aimModal.hidden = true;
  } else {
    updateRoleBanner();
    aimBtn.hidden = state.role !== "impostor";
    if (state.pendingRoleFlash) {
      showRoleFlash(state.pendingRoleFlash);
      state.pendingRoleFlash = "";
    }
  }
}

function getNickByConn(connId) {
  const players = (state.lobby && state.lobby.players) || {};
  const player = players[connId];
  if (player && player.nick) {
    return player.nick;
  }
  return connId;
}

export function updateLobbyView(lobby) {
  state.lobby = lobby;
  if (!lobby) {
    return;
  }
  const roomId = lobby.room_id || "";
  $("lobby-room-name").textContent = lobby.name || "Room";
  $("nick-room-id").textContent = roomId;
  $("lobby-title").textContent = roomId ? `ROOM [${roomId}]` : "ROOM [ID]";
  $("nick-title").textContent = roomId ? `NICKNAME [${roomId}]` : "NICKNAME [ROOM]";

  const playersList = $("players-list");
  playersList.innerHTML = "";
  const players = lobby.players || {};
  const isHost = lobby.host && lobby.host === state.connId;
  Object.keys(players)
    .sort()
    .forEach((connId) => {
      const player = players[connId];
      const li = document.createElement("li");
      const meta = document.createElement("div");
      meta.className = "player-meta";
      const name = document.createElement("div");
      const nick = player.nick || "unknown";
      const nameTags = [];
      if (connId === lobby.host) {
        nameTags.push("HOST");
      }
      if (connId === state.connId) {
        nameTags.push("YOU");
      }
      const tagText = formatTags(nameTags);
      name.textContent = tagText ? `${nick} ${tagText}` : nick;
      const tag = document.createElement("div");
      tag.className = "player-tag";
      tag.textContent = player.ready ? "[READY]" : "[NOT READY]";
      meta.appendChild(name);
      meta.appendChild(tag);
      li.appendChild(meta);

      if (isHost && connId !== lobby.host) {
        const kickBtn = document.createElement("button");
        kickBtn.type = "button";
        kickBtn.className = "button-outline";
        kickBtn.dataset.connId = connId;
        kickBtn.textContent = "Kick";
        li.appendChild(kickBtn);
      }
      playersList.appendChild(li);
    });

  const me = players[state.connId];
  if (me) {
    $("ready-btn").textContent = me.ready ? "Not ready" : "Ready";
  } else {
    $("ready-btn").textContent = "Ready";
  }

  const settings = lobby.settings || {};
  $("setting-max-players").value = settings.max_players ?? "";
  $("setting-turn-duration").value = settings.turn_duration ?? "";
  $("setting-vote-duration").value = settings.round_time ?? "";

  $("host-controls").hidden = !isHost;
  const allReady = Object.values(players).length > 0 && Object.values(players).every((p) => p.ready);
  $("start-game-btn").disabled = !allReady;
  renderTurn();
  renderVoting();
}

function showRoleFlash(text) {
  if (!text) {
    return;
  }
  const flash = $("role-flash");
  $("role-flash-text").textContent = text;
  flash.hidden = false;
  if (roleFlashTimer) {
    clearTimeout(roleFlashTimer);
  }
  roleFlashTimer = setTimeout(() => {
    flash.hidden = true;
  }, 3000);
}

function updateRoleBanner() {
  const banner = $("role-banner");
  if (!state.role) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  if (state.role === "impostor") {
    banner.textContent = "ROLE [IMPOSTOR]";
  } else {
    banner.textContent = `WORD [${state.word || "--"}]`;
  }
  banner.hidden = false;
}

export function updateRole(role, word) {
  state.role = role;
  state.word = word || null;
  if (word) {
    state.lastWord = word;
  }
  const aimBtn = $("aim-btn");
  const showRoleUi = state.screen === "game" || state.screen === "voting";
  state.pendingRoleFlash = "";
  if (role === "impostor") {
    state.pendingRoleFlash = "ROLE [IMPOSTOR]";
    aimBtn.hidden = !showRoleUi;
    if (showRoleUi) {
      showRoleFlash(state.pendingRoleFlash);
      state.pendingRoleFlash = "";
    }
  } else if (role) {
    state.pendingRoleFlash = word ? `WORD [${word}]` : "WORD [--]";
    aimBtn.hidden = true;
    if (showRoleUi) {
      showRoleFlash(state.pendingRoleFlash);
      state.pendingRoleFlash = "";
    }
  } else {
    aimBtn.hidden = true;
  }
  updateRoleBanner();
}

export function renderTurn() {
  const metaEl = $("turn-meta");
  const statusEl = $("turn-status");
  const timerEl = $("turn-timer");
  const inputWrap = $("turn-input");
  const input = $("turn-word");
  const submitBtn = $("turn-submit-btn");
  const roundList = $("round-words");
  const titleEl = $("game-title");

  const round = state.turnRound;
  const order = state.turnOrder || [];
  const index = state.turnIndex;
  const connId = state.turnConnId;
  const phase = state.turnPhase;
  const remaining = state.turnRemaining;

  titleEl.textContent = round ? `ROUND [${round}]` : "ROUND [--]";

  const metaParts = [];
  if (index !== null && index !== undefined) {
    const total = order.length;
    metaParts.push(total ? `TURN [${index + 1}/${total}]` : `TURN [${index + 1}]`);
  }
  metaEl.textContent = metaParts.join(" ");

  const currentLabel = connId ? getNickByConn(connId) : "Unknown";
  let status = "[WAIT] ROUND START";
  if (phase === "active") {
    status =
      connId === state.connId
        ? "[TURN] SUBMIT YOUR WORD"
        : `[WAIT] ${currentLabel}`;
  } else if (phase === "paused" || phase === "grace") {
    status = `[PAUSED] ${currentLabel}`;
  } else if (phase === "voting") {
    status = "[VOTE] IN PROGRESS";
  } else if (phase) {
    status = "[WAIT] NEXT TURN";
  }
  statusEl.textContent = status;

  if (remaining !== null && remaining !== undefined) {
    const label = phase === "grace" || phase === "paused" ? "GRACE" : "TIME";
    const total =
      phase === "grace" || phase === "paused"
        ? state.turnGrace
        : state.turnDuration;
    timerEl.textContent = formatTimeBar(label, remaining, total ?? remaining);
  } else {
    timerEl.textContent = "";
  }

  const canSubmit = phase === "active" && connId === state.connId;
  inputWrap.hidden = !canSubmit;
  input.disabled = !canSubmit;
  submitBtn.disabled = !canSubmit || state.turnBusy;

  roundList.innerHTML = "";
  const words = state.turnWords || [];
  if (!words.length) {
    const li = document.createElement("li");
    li.textContent = "NO WORDS YET.";
    roundList.appendChild(li);
  } else {
    words.forEach((entry) => {
      const li = document.createElement("li");
      li.textContent = `${getNickByConn(entry.conn_id)} :: ${entry.word}`;
      roundList.appendChild(li);
    });
  }
}

function renderWordHistory() {
  const historyList = $("word-history");
  historyList.innerHTML = "";
  const history = state.wordHistory || [];
  if (!history.length) {
    const li = document.createElement("li");
    li.textContent = "NO WORDS LOGGED.";
    historyList.appendChild(li);
    return;
  }
  const grouped = {};
  history.forEach((entry) => {
    const key = entry.conn_id;
    if (!grouped[key]) {
      grouped[key] = [];
    }
    grouped[key].push(entry.word);
  });
  Object.keys(grouped)
    .sort()
    .forEach((connId) => {
      const li = document.createElement("li");
      li.textContent = `${getNickByConn(connId)} :: ${grouped[connId].join(", ")}`;
      historyList.appendChild(li);
    });
}

export function renderVoting() {
  const active = state.votingActive;
  $("screen-voting").hidden = !active;
  if (!active) {
    return;
  }
  const roundLabel = state.turnRound ?? "--";
  $("voting-title").textContent = `VOTING [ROUND ${roundLabel}]`;
  const voters = state.voters || [];
  const alreadyVoted = !!(state.votes && state.votes[state.connId]);
  const canVote = voters.includes(state.connId) && !alreadyVoted;
  if (alreadyVoted) {
    $("voting-status").textContent = "[VOTE] SUBMITTED";
  } else {
    $("voting-status").textContent = canVote
      ? "[VOTE] CAST YOUR VOTE"
      : "[VOTE] IN PROGRESS";
  }

  const remaining = state.turnRemaining;
  $("voting-timer").textContent =
    remaining !== null && remaining !== undefined
      ? formatTimeBar("TIME", remaining, state.voteDuration ?? remaining)
      : "";

  const buttonsWrap = $("vote-buttons");
  buttonsWrap.innerHTML = "";
  const skipBtn = document.createElement("button");
  skipBtn.type = "button";
  skipBtn.dataset.connId = "skip";
  skipBtn.textContent = "SKIP [VOTE]";
  skipBtn.disabled = !canVote;
  buttonsWrap.appendChild(skipBtn);
  voters.forEach((connId) => {
    if (connId === state.connId) {
      return;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.connId = connId;
    button.textContent = getNickByConn(connId);
    button.disabled = !canVote;
    buttonsWrap.appendChild(button);
  });

  renderWordHistory();
}

function formatWinner(winner) {
  if (winner === "crew") {
    return "Crew";
  }
  if (winner === "impostor") {
    return "Impostor";
  }
  return "No winner";
}

function formatReason(result) {
  if (!result) {
    return "Unknown";
  }
  if (result.reason === "impostor_guessed") {
    return "Impostor guessed the word";
  }
  if (result.reason === "impostor_failed_guess") {
    return "Impostor missed the guess";
  }
  if (result.reason === "impostor_eliminated") {
    return "Impostor eliminated";
  }
  if (result.reason === "crew_eliminated") {
    return "Crew eliminated";
  }
  if (result.reason === "no_majority") {
    return "No majority";
  }
  return result.reason || "Unknown";
}

export function renderEndScreen(result) {
  state.gameResult = result || null;
  const endTitle = $("end-title");
  if (!result) {
    endTitle.textContent = "GAME OVER [PENDING]";
    $("end-outcome").textContent = "Awaiting results.";
    $("end-winner").textContent = "Unknown";
    $("end-reason").textContent = "Unknown";
    $("end-impostor").textContent = "Unknown";
    $("end-word").textContent = "Unknown";
    $("end-voted-out").textContent = "-";
    $("end-guess").textContent = "-";
    return;
  }
  const winnerLabel = formatWinner(result.winner);
  const reasonLabel = formatReason(result);
  const impostorLabel = result.impostor ? getNickByConn(result.impostor) : "Unknown";
  const wordLabel = result.word || state.lastWord || "Unknown";
  const votedOutLabel = result.voted_out ? getNickByConn(result.voted_out) : "-";
  const guessLabel = result.guess ? result.guess : "-";
  endTitle.textContent = `GAME OVER [${winnerLabel.toUpperCase()}]`;

  if (result.reason === "impostor_guessed") {
    $("end-outcome").textContent = "Impostor guessed the word.";
  } else if (result.reason === "impostor_failed_guess") {
    $("end-outcome").textContent = "Impostor missed the guess.";
  } else if (result.reason === "impostor_eliminated") {
    $("end-outcome").textContent = "Impostor eliminated.";
  } else if (result.reason === "crew_eliminated") {
    $("end-outcome").textContent = "Crew eliminated.";
  } else {
    $("end-outcome").textContent = "Game ended.";
  }

  $("end-winner").textContent = winnerLabel;
  $("end-reason").textContent = reasonLabel;
  $("end-impostor").textContent = impostorLabel;
  $("end-word").textContent = wordLabel;
  $("end-voted-out").textContent = votedOutLabel;
  $("end-guess").textContent = guessLabel;
}

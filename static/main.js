import { api } from "./api.js";
import { $ } from "./dom.js";
import { state } from "./state.js";
import { clearResume, loadResume } from "./storage.js";
import { connectWs } from "./ws.js";
import {
  renderEndScreen,
  renderTurn,
  renderVoting,
  setScreen,
  setStatus,
  updateLobbyView,
  updateRole,
} from "./ui.js";

$("create-room-btn").addEventListener("click", async () => {
  try {
    const name = $("create-room-name").value.trim();
    if (!name) {
      setStatus("Enter a room name.");
      return;
    }
    const data = await api("/rooms/", "POST", { name });
    $("created-room-id").textContent = data.room_id;
    setStatus("Room created.");
    clearResume();
    connectWs({ roomId: data.room_id, nick: "", token: null });
  } catch (err) {
    setStatus("Create room failed: " + err.message);
  }
});

$("join-room-btn").addEventListener("click", () => {
  const roomId = $("join-room-id").value.trim();
  if (!roomId) {
    setStatus("Room ID is required.");
    return;
  }
  clearResume();
  connectWs({ roomId, nick: "", token: null });
});

$("nick-save-btn").addEventListener("click", async () => {
  const nickname = $("nick-input").value.trim();
  if (!nickname) {
    setStatus("Enter a nickname.");
    return;
  }
  if (state.nicknameBusy) {
    return;
  }
  try {
    state.nicknameBusy = true;
    const data = await api(`/rooms/${encodeURIComponent(state.roomId)}/nick`, "POST", {
      conn_id: state.connId,
      nickname,
    });
    updateLobbyView(data);
    state.nick = nickname;
    state.needsNickname = false;
    setScreen("lobby");
    setStatus("Nickname saved.");
  } catch (err) {
    setStatus("Nickname update failed: " + err.message);
  } finally {
    state.nicknameBusy = false;
  }
});

$("ready-btn").addEventListener("click", async () => {
  if (state.readyBusy) {
    return;
  }
  try {
    state.readyBusy = true;
    const me = state.lobby && state.lobby.players && state.lobby.players[state.connId];
    const ready = !(me && me.ready);
    const data = await api(`/rooms/${encodeURIComponent(state.roomId)}/ready`, "POST", {
      conn_id: state.connId,
      ready,
    });
    updateLobbyView(data);
    setStatus(ready ? "Ready." : "Not ready.");
  } catch (err) {
    setStatus("Ready update failed: " + err.message);
  } finally {
    state.readyBusy = false;
  }
});

$("settings-save-btn").addEventListener("click", async () => {
  if (state.settingsBusy) {
    return;
  }
  try {
    state.settingsBusy = true;
    const maxPlayers = parseInt($("setting-max-players").value, 10);
    const turnDuration = parseInt($("setting-turn-duration").value, 10);
    const voteDuration = parseInt($("setting-vote-duration").value, 10);
    const payload = {
      conn_id: state.connId,
      max_players: Number.isFinite(maxPlayers) && maxPlayers > 0 ? maxPlayers : null,
      turn_duration:
        Number.isFinite(turnDuration) && turnDuration > 0 ? turnDuration : null,
      round_time:
        Number.isFinite(voteDuration) && voteDuration > 0 ? voteDuration : null,
    };
    await api(`/rooms/${encodeURIComponent(state.roomId)}/settings`, "POST", payload);
    setStatus("Settings updated.");
  } catch (err) {
    setStatus("Settings update failed: " + err.message);
  } finally {
    state.settingsBusy = false;
  }
});

$("start-game-btn").addEventListener("click", async () => {
  try {
    await api(`/rooms/${encodeURIComponent(state.roomId)}/start`, "POST", {
      conn_id: state.connId,
    });
    setStatus("Game started.");
  } catch (err) {
    setStatus("Start game failed: " + err.message);
  }
});

$("players-list").addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) {
    return;
  }
  const connId = target.dataset.connId;
  if (!connId) {
    return;
  }
  try {
    await api(`/rooms/${encodeURIComponent(state.roomId)}/kick`, "POST", {
      conn_id: state.connId,
      target_conn_id: connId,
    });
    setStatus("Player kicked.");
  } catch (err) {
    setStatus("Kick failed: " + err.message);
  }
});

$("turn-submit-btn").addEventListener("click", async () => {
  if (state.turnPhase !== "active" || state.turnConnId !== state.connId) {
    setStatus("It is not your turn.");
    return;
  }
  const word = $("turn-word").value.trim();
  if (!word) {
    setStatus("Enter a word.");
    return;
  }
  if (state.turnBusy) {
    return;
  }
  try {
    state.turnBusy = true;
    renderTurn();
    await api(`/rooms/${encodeURIComponent(state.roomId)}/turn-word`, "POST", {
      conn_id: state.connId,
      word,
    });
    $("turn-word").value = "";
    setStatus("Word submitted.");
  } catch (err) {
    setStatus("Submit word failed: " + err.message);
  } finally {
    state.turnBusy = false;
    renderTurn();
  }
});

$("vote-buttons").addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) {
    return;
  }
  const connId = target.dataset.connId;
  if (!connId) {
    return;
  }
  if (!state.votingActive) {
    return;
  }
  if (state.votes && state.votes[state.connId]) {
    setStatus("Vote already submitted.");
    return;
  }
  try {
    await api(`/rooms/${encodeURIComponent(state.roomId)}/vote`, "POST", {
      conn_id: state.connId,
      target_conn_id: connId,
    });
    setStatus("Vote cast.");
  } catch (err) {
    setStatus("Vote failed: " + err.message);
  }
});

$("aim-btn").addEventListener("click", () => {
  if (state.role !== "impostor") {
    return;
  }
  $("aim-modal").hidden = false;
  $("aim-guess-word").focus();
});

$("aim-cancel-btn").addEventListener("click", () => {
  $("aim-modal").hidden = true;
  $("aim-guess-word").value = "";
});

$("aim-submit-btn").addEventListener("click", async () => {
  if (state.role !== "impostor") {
    setStatus("Only the impostor can guess.");
    return;
  }
  const guess = $("aim-guess-word").value.trim();
  if (!guess) {
    setStatus("Enter a guess.");
    return;
  }
  try {
    await api(`/rooms/${encodeURIComponent(state.roomId)}/guess`, "POST", {
      conn_id: state.connId,
      guess,
    });
    $("aim-modal").hidden = true;
    $("aim-guess-word").value = "";
    setStatus("Guess submitted.");
  } catch (err) {
    setStatus("Guess failed: " + err.message);
  }
});

$("end-back-btn").addEventListener("click", () => {
  setScreen("lobby");
  setStatus("Back in lobby.");
});

setScreen("setup");

const stored = loadResume();
if (stored.token && stored.roomId) {
  setStatus("Resuming session...");
  connectWs({ roomId: stored.roomId, nick: null, token: stored.token });
} else {
  renderEndScreen(null);
  updateRole(null, null);
  renderTurn();
  renderVoting();
}

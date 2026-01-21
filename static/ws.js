import { api } from "./api.js";
import { $ } from "./dom.js";
import { state } from "./state.js";
import { clearResume } from "./storage.js";
import {
  renderEndScreen,
  renderTurn,
  renderVoting,
  setScreen,
  setStatus,
  updateLobbyView,
  updateRole,
} from "./ui.js";

function resetTurnState() {
  state.turnRound = null;
  state.turnOrder = [];
  state.turnIndex = null;
  state.turnConnId = "";
  state.turnPhase = null;
  state.turnRemaining = null;
  state.turnDuration = null;
  state.turnGrace = null;
  state.voteDuration = null;
  state.turnWords = [];
  state.turnBusy = false;
}

function resetGameState() {
  resetTurnState();
  state.wordHistory = [];
  state.votingActive = false;
  state.voters = [];
  state.votes = {};
  state.tally = {};
  state.lastVotingResult = null;
}

async function refreshLobby() {
  if (!state.roomId) {
    return;
  }
  const data = await api(`/rooms/${encodeURIComponent(state.roomId)}/lobby`);
  updateLobbyView(data);
}

export function connectWs({ roomId, nick, token }) {
  if (state.ws) {
    state.ws.close();
  }
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  let query = "";
  if (token) {
    query = "token=" + encodeURIComponent(token);
  } else if (nick) {
    query = "nick=" + encodeURIComponent(nick);
  }
  const wsUrl = `${protocol}://${location.host}/rooms/${encodeURIComponent(
    roomId
  )}/ws${query ? `?${query}` : ""}`;

  const ws = new WebSocket(wsUrl);
  state.ws = ws;
  state.roomId = roomId;
  state.nick = nick || "";
  state.connId = "";
  state.pendingResumeToken = token || "";
  state.awaitingWelcome = true;
  state.needsNickname = false;
  resetGameState();
  updateRole(null, null);
  setStatus("Connecting...");

  ws.onopen = () => {
    setStatus("Connected.");
  };

  ws.onmessage = async (event) => {
    let payload = null;
    try {
      payload = JSON.parse(event.data);
    } catch {
      payload = { type: "text", text: event.data };
    }

    if (payload.type === "welcome") {
      state.connId = payload.conn_id;
      state.roomId = payload.room_id;
      state.nick = payload.nick || "";
      state.awaitingWelcome = false;
      if (state.pendingResumeToken) {
        clearResume();
        state.pendingResumeToken = "";
      }
      state.needsNickname = !state.nick || state.nick === "unknown";
      await refreshLobby();
      if (state.needsNickname) {
        $("nick-input").value = "";
      }
      setScreen(state.needsNickname ? "nick" : "lobby");
      setStatus("Connected to room.");
    }

    if (payload.type === "game_started") {
      state.gameResult = null;
      state.lastWord = null;
      resetGameState();
      $("aim-modal").hidden = true;
      renderEndScreen(null);
      renderTurn();
      renderVoting();
      setScreen("game");
      setStatus("Game started.");
    }

    if (payload.type === "lobby_state") {
      updateLobbyView(payload.state);
    }

    if (payload.type === "user_joined" || payload.type === "user_left") {
      await refreshLobby();
    }

    if (payload.type === "user_renamed") {
      await refreshLobby();
    }

    if (payload.type === "role") {
      if (payload.role === "impostor") {
        updateRole("impostor", null);
      } else {
        updateRole("crew", payload.word || null);
      }
    }

    if (payload.type === "turn_state") {
      const turnState = payload.state || {};
      state.turnRound = turnState.round ?? null;
      state.turnOrder = turnState.order || [];
      state.turnIndex =
        turnState.turn_index !== undefined ? turnState.turn_index : null;
      state.turnConnId = turnState.current_conn_id || "";
      state.turnPhase = turnState.phase || null;
      state.turnRemaining =
        turnState.remaining !== undefined ? turnState.remaining : null;
      state.turnDuration =
        turnState.turn_duration !== undefined
          ? turnState.turn_duration
          : state.turnDuration;
      state.voteDuration =
        turnState.vote_duration !== undefined
          ? turnState.vote_duration
          : state.voteDuration;
      state.turnGrace =
        turnState.turn_grace !== undefined
          ? turnState.turn_grace
          : state.turnGrace;
      state.turnWords = turnState.words || [];
      state.wordHistory = turnState.history || [];
      if (turnState.phase === "voting") {
        state.votingActive = true;
        state.voters = turnState.voters || [];
        state.votes = turnState.votes || {};
        state.tally = turnState.tally || {};
        state.lastVotingResult = null;
        renderVoting();
        setScreen("voting");
      } else {
        state.votingActive = false;
        state.voters = [];
        state.votes = {};
        state.tally = {};
        state.lastVotingResult = null;
        renderVoting();
      }
      if (turnState.phase !== "voting" && state.role) {
        setScreen("game");
      }
      renderTurn();
    }

    if (payload.type === "round_started") {
      state.turnRound = payload.round;
      state.turnOrder = payload.order || [];
      state.turnIndex = null;
      state.turnConnId = "";
      state.turnPhase = null;
      state.turnRemaining = null;
      state.turnDuration =
        payload.turn_duration !== undefined
          ? payload.turn_duration
          : state.turnDuration;
      state.turnWords = [];
      state.lastVotingResult = null;
      renderTurn();
      setScreen("game");
    }

    if (payload.type === "turn_started") {
      state.turnRound = payload.round;
      state.turnIndex = payload.turn_index;
      state.turnConnId = payload.conn_id;
      state.turnPhase = "active";
      state.turnRemaining = payload.turn_duration ?? state.turnRemaining;
      state.turnDuration =
        payload.turn_duration !== undefined
          ? payload.turn_duration
          : state.turnDuration;
      renderTurn();
      setScreen("game");
    }

    if (payload.type === "turn_timer") {
      state.turnPhase = payload.phase;
      state.turnRemaining = payload.remaining;
      if (payload.phase === "voting") {
        renderVoting();
      }
      renderTurn();
    }

    if (payload.type === "turn_paused") {
      state.turnPhase = "paused";
      state.turnIndex = payload.turn_index;
      state.turnConnId = payload.conn_id;
      state.turnRemaining = payload.remaining;
      state.turnGrace =
        payload.remaining !== undefined ? payload.remaining : state.turnGrace;
      renderTurn();
    }

    if (payload.type === "turn_resumed") {
      state.turnPhase = "active";
      state.turnIndex = payload.turn_index;
      state.turnConnId = payload.conn_id;
      state.turnRemaining = payload.remaining;
      state.turnDuration =
        payload.remaining !== undefined ? payload.remaining : state.turnDuration;
      renderTurn();
    }

    if (payload.type === "turn_ended") {
      state.turnPhase = "ended";
      state.turnIndex = payload.turn_index;
      state.turnConnId = payload.conn_id;
      state.turnRemaining = null;
      renderTurn();
    }

    if (payload.type === "turn_word_submitted") {
      state.turnWords = [...(state.turnWords || []), payload];
      state.wordHistory = [...(state.wordHistory || []), payload];
      renderTurn();
      if (state.votingActive) {
        renderVoting();
      }
    }

    if (payload.type === "voting_started") {
      state.votingActive = true;
      state.voters = payload.voters || [];
      state.votes = {};
      state.tally = {};
      state.lastVotingResult = null;
      state.turnPhase = "voting";
      state.turnRemaining = payload.vote_duration ?? null;
      state.voteDuration =
        payload.vote_duration !== undefined
          ? payload.vote_duration
          : state.voteDuration;
      renderVoting();
      setScreen("voting");
    }

    if (payload.type === "vote_cast") {
      state.votes = payload.votes || {};
      state.tally = payload.tally || {};
      renderVoting();
    }

    if (payload.type === "voting_result") {
      state.votingActive = false;
      state.lastVotingResult = payload.result || null;
      renderVoting();
    }

    if (payload.type === "game_ended") {
      resetGameState();
      state.pendingRoleFlash = "";
      renderVoting();
      renderTurn();
      renderEndScreen(payload.result || null);
      updateRole(null, null);
      $("aim-modal").hidden = true;
      setScreen("end");
      setStatus("Game ended.");
    }

    if (payload.type === "kicked") {
      setStatus("You were kicked from the room.");
      if (state.ws) {
        state.ws.close();
      }
    }
  };

  ws.onclose = () => {
    if (state.awaitingWelcome && state.pendingResumeToken) {
      clearResume();
      state.pendingResumeToken = "";
      state.awaitingWelcome = false;
      setStatus("Resume failed. Please join again.");
    } else {
      setStatus("Disconnected.");
    }
    resetGameState();
    state.pendingRoleFlash = "";
    renderVoting();
    renderTurn();
    renderEndScreen(null);
    updateRole(null, null);
    $("aim-modal").hidden = true;
    state.gameResult = null;
    state.lastWord = null;
    setScreen("setup");
  };

  ws.onerror = () => {
    setStatus("Connection error.");
  };
}

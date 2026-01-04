(function () {
  const $ = (id) => document.getElementById(id);
  const STORAGE_TOKEN = "impostor_resume_token";
  const STORAGE_ROOM = "impostor_resume_room";

  const state = {
    ws: null,
    roomId: "",
    connId: "",
    nick: "",
    lobby: null,
    role: null,
    word: null,
    pendingResumeToken: "",
    awaitingWelcome: false,
    readyBusy: false,
    votingActive: false,
    voters: [],
    votes: {},
    tally: {},
    lastVotingResult: null,
  };

  function setStatus(message) {
    $("status").textContent = message;
  }

  function setScreen(name) {
    $("screen-setup").hidden = name !== "setup";
    $("screen-lobby").hidden = name !== "lobby";
  }

  function updateLobbyView(lobby) {
    state.lobby = lobby;
    if (!lobby) {
      return;
    }
    $("lobby-room-name").textContent = lobby.name || "Room";
    $("lobby-room-id").textContent = lobby.room_id || "";

    const playersList = $("players-list");
    playersList.innerHTML = "";
    const players = lobby.players || {};
    Object.keys(players)
      .sort()
      .forEach((connId) => {
        const player = players[connId];
        const li = document.createElement("li");
        const nick = player.nick || "unknown";
        const ready = player.ready ? "ready" : "not ready";
        const hostTag = connId === lobby.host ? " (host)" : "";
        const selfTag = connId === state.connId ? " (you)" : "";
        li.textContent = `${nick} - ${ready}${hostTag}${selfTag}`;
        playersList.appendChild(li);
      });

    const me = players[state.connId];
    if (me) {
      $("ready-flag").checked = !!me.ready;
    }

    const allReady = Object.values(players).every((p) => p.ready);
    const isHost = lobby.host && lobby.host === state.connId;
    $("start-game-btn").hidden = !isHost;
    $("start-game-btn").disabled = !allReady;
    $("end-game-btn").hidden = !isHost;
    renderVoting();
  }

  function updateRole(role, word) {
    state.role = role;
    state.word = word || null;
    $("role-value").textContent = role || "unknown";
    $("word-value").textContent = word || "unknown";
    $("screen-game").hidden = !role;
    renderVoting();
  }

  function getNickByConn(connId) {
    const players = (state.lobby && state.lobby.players) || {};
    const player = players[connId];
    if (player && player.nick) {
      return player.nick;
    }
    return connId;
  }

  function formatVoteTarget(target) {
    if (target === "skip") {
      return "Skip";
    }
    return getNickByConn(target);
  }

  function renderVoting() {
    const section = $("screen-voting");
    if (!section) {
      return;
    }
    const active = state.votingActive;
    const result = state.lastVotingResult;
    section.hidden = !active && !result;

    const voters = state.voters || [];
    const canVote = active && voters.includes(state.connId);
    const statusEl = $("voting-status");
    if (active) {
      statusEl.textContent = canVote
        ? "Voting in progress."
        : "Voting in progress (not eligible).";
    } else if (result) {
      statusEl.textContent = "Voting ended.";
    } else {
      statusEl.textContent = "";
    }

    const targetSelect = $("vote-target");
    targetSelect.innerHTML = "";
    if (voters.length) {
      const skipOption = document.createElement("option");
      skipOption.value = "skip";
      skipOption.textContent = "Skip";
      targetSelect.appendChild(skipOption);
      voters.forEach((connId) => {
        const option = document.createElement("option");
        option.value = connId;
        option.textContent = getNickByConn(connId);
        targetSelect.appendChild(option);
      });
    }
    targetSelect.disabled = !canVote;
    $("vote-btn").disabled = !canVote;

    const voteList = $("vote-list");
    voteList.innerHTML = "";
    Object.keys(state.votes || {})
      .sort()
      .forEach((voter) => {
        const li = document.createElement("li");
        li.textContent = `${getNickByConn(voter)} -> ${formatVoteTarget(
          state.votes[voter]
        )}`;
        voteList.appendChild(li);
      });

    const tallyList = $("vote-tally");
    tallyList.innerHTML = "";
    Object.keys(state.tally || {})
      .sort()
      .forEach((target) => {
        const li = document.createElement("li");
        li.textContent = `${formatVoteTarget(target)}: ${state.tally[target]}`;
        tallyList.appendChild(li);
      });

    const resultEl = $("voting-result");
    if (result) {
      if (result.winner) {
        resultEl.textContent = `Voted out: ${formatVoteTarget(
          result.voted_out
        )}. Winner: ${result.winner}.`;
      } else {
        resultEl.textContent = "No majority. New round starting.";
      }
    } else {
      resultEl.textContent = "";
    }
  }

  function saveResume(token, roomId) {
    localStorage.setItem(STORAGE_TOKEN, token);
    localStorage.setItem(STORAGE_ROOM, roomId);
  }

  function loadResume() {
    return {
      token: localStorage.getItem(STORAGE_TOKEN) || "",
      roomId: localStorage.getItem(STORAGE_ROOM) || "",
    };
  }

  function clearResume() {
    localStorage.removeItem(STORAGE_TOKEN);
    localStorage.removeItem(STORAGE_ROOM);
  }

  async function api(path, method, body) {
    const options = { method: method || "GET" };
    if (body !== undefined) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    const response = await fetch(path, options);
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    if (!response.ok) {
      const detail = data && data.detail ? data.detail : text;
      throw new Error(detail || response.statusText);
    }
    return data;
  }

  async function refreshLobby() {
    if (!state.roomId) {
      return;
    }
    const data = await api(`/rooms/${encodeURIComponent(state.roomId)}/lobby`);
    updateLobbyView(data);
  }

  function connectWs({ roomId, nick, token }) {
    if (state.ws) {
      state.ws.close();
    }
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const query = token
      ? "token=" + encodeURIComponent(token)
      : "nick=" + encodeURIComponent(nick);
    const wsUrl = `${protocol}://${location.host}/rooms/${encodeURIComponent(
      roomId
    )}/ws?${query}`;

    const ws = new WebSocket(wsUrl);
    state.ws = ws;
    state.roomId = roomId;
    state.nick = nick || "";
    state.connId = "";
    state.pendingResumeToken = token || "";
    state.awaitingWelcome = true;
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
        state.nick = payload.nick;
        state.awaitingWelcome = false;
        if (state.pendingResumeToken) {
          clearResume();
          state.pendingResumeToken = "";
        }
        await refreshLobby();
        setScreen("lobby");
        setStatus("Connected to room.");
      }

      if (payload.type === "lobby_state") {
        updateLobbyView(payload.state);
      }

      if (payload.type === "user_joined" || payload.type === "user_left") {
        await refreshLobby();
      }

      if (payload.type === "role") {
        if (payload.role === "impostor") {
          updateRole("impostor", null);
        } else {
          updateRole("crew", payload.word || null);
        }
      }

      if (payload.type === "round_started") {
        state.lastVotingResult = null;
        renderVoting();
      }

      if (payload.type === "voting_started") {
        state.votingActive = true;
        state.voters = payload.voters || [];
        state.votes = {};
        state.tally = {};
        state.lastVotingResult = null;
        renderVoting();
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

      if (payload.type === "msg") {
        const li = document.createElement("li");
        li.textContent = `${payload.nick}: ${payload.text}`;
        $("chat-log").appendChild(li);
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
      state.votingActive = false;
      state.voters = [];
      state.votes = {};
      state.tally = {};
      state.lastVotingResult = null;
      renderVoting();
      setScreen("setup");
    };

    ws.onerror = () => {
      setStatus("Connection error.");
    };
  }

  $("create-room-btn").addEventListener("click", async () => {
    try {
      const name = $("create-room-name").value.trim();
      const data = await api("/rooms/", "POST", { name });
      $("created-room-id").textContent = data.room_id;
      $("join-room-id").value = data.room_id;
      setStatus("Room created.");
    } catch (err) {
      setStatus("Create room failed: " + err.message);
    }
  });

  $("join-room-btn").addEventListener("click", () => {
    const roomId = $("join-room-id").value.trim();
    const nick = $("join-nick").value.trim();
    if (!roomId || !nick) {
      setStatus("Room ID and nickname are required.");
      return;
    }
    clearResume();
    connectWs({ roomId, nick, token: null });
  });

  $("ready-flag").addEventListener("change", async () => {
    if (state.readyBusy) {
      return;
    }
    try {
      state.readyBusy = true;
      const ready = $("ready-flag").checked;
      const data = await api(`/rooms/${encodeURIComponent(state.roomId)}/ready`, "POST", {
        conn_id: state.connId,
        ready,
      });
      updateLobbyView(data);
      setStatus("Ready updated.");
    } catch (err) {
      $("ready-flag").checked = !$("ready-flag").checked;
      setStatus("Ready update failed: " + err.message);
    } finally {
      state.readyBusy = false;
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

  $("end-game-btn").addEventListener("click", async () => {
    try {
      await api(`/rooms/${encodeURIComponent(state.roomId)}/end`, "POST", {
        result: null,
      });
      updateRole(null, null);
      state.votingActive = false;
      state.voters = [];
      state.votes = {};
      state.tally = {};
      state.lastVotingResult = null;
      renderVoting();
      setStatus("Game ended.");
    } catch (err) {
      setStatus("End game failed: " + err.message);
    }
  });

  $("vote-btn").addEventListener("click", async () => {
    if (!state.votingActive) {
      return;
    }
    const target = $("vote-target").value;
    if (!target) {
      setStatus("Select a vote target.");
      return;
    }
    try {
      await api(`/rooms/${encodeURIComponent(state.roomId)}/vote`, "POST", {
        conn_id: state.connId,
        target_conn_id: target,
      });
      setStatus("Vote cast.");
    } catch (err) {
      setStatus("Vote failed: " + err.message);
    }
  });

  $("chat-send-btn").addEventListener("click", () => {
    const text = $("chat-text").value.trim();
    if (!text) {
      return;
    }
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      setStatus("Socket is not open.");
      return;
    }
    state.ws.send(text);
    $("chat-text").value = "";
  });

  $("leave-btn").addEventListener("click", async () => {
    try {
      const data = await api(`/rooms/${encodeURIComponent(state.roomId)}/disconnect`, "POST", {
        conn_id: state.connId,
      });
      saveResume(data.token, state.roomId);
      if (state.ws) {
        state.ws.close();
      }
      setStatus("Session saved.");
    } catch (err) {
      setStatus("Leave failed: " + err.message);
    }
  });

  setScreen("setup");

  const stored = loadResume();
  if (stored.token && stored.roomId) {
    setStatus("Resuming session...");
    connectWs({ roomId: stored.roomId, nick: null, token: stored.token });
  }
})();

const STORAGE_TOKEN = "impostor_resume_token";
const STORAGE_ROOM = "impostor_resume_room";

export function saveResume(token, roomId) {
  localStorage.setItem(STORAGE_TOKEN, token);
  localStorage.setItem(STORAGE_ROOM, roomId);
}

export function loadResume() {
  return {
    token: localStorage.getItem(STORAGE_TOKEN) || "",
    roomId: localStorage.getItem(STORAGE_ROOM) || "",
  };
}

export function clearResume() {
  localStorage.removeItem(STORAGE_TOKEN);
  localStorage.removeItem(STORAGE_ROOM);
}

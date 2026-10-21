// Line icons (24 × 24, stroke), drawn inline so the app needs no icon font or outside files.
const PATHS: Record<string, string> = {
  door: "M5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17M3 21h18M14 12v.01",
  message: "M4 5h16v11H8l-4 4z",
  history: "M12 8v4l3 2M3.05 11a9 9 0 1 1 .5 4M3 4v5h5",
  home: "M3 11 12 3l9 8M5 9.5V21h14V9.5M10 21v-6h4v6",
  bell: "M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 21h4",
  "bell-off": "M6 16V11a6 6 0 0 1 9.5-4.9M18 11v5l2 2H4M10 21h4M3 3l18 18",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
  radar: "M12 12m-1 0a1 1 0 1 0 2 0 1 1 0 1 0-2 0M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M5.6 5.6a9 9 0 0 0 0 12.8M18.4 5.6a9 9 0 0 1 0 12.8",
  play: "M7 4v16l13-8z",
  share: "M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M12 3v13M7 8l5-5 5 5",
  trash: "M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3",
  pause: "M7 4h4v16H7zM14 4h4v16h-4z",
  mic: "M9 5a3 3 0 0 1 6 0v6a3 3 0 0 1-6 0zM5 11a7 7 0 0 0 14 0M12 18v3",
  text: "M4 6h16M4 12h10M4 18h7",
  image: "M4 5h16v14H4zM4 16l5-5 4 4 2-2 5 5M15 9.5v.01",
  hand: "M12 3v9M8 6v7M16 6v7M5 10v4a7 7 0 0 0 14 0V8",
  key: "M15 9a4 4 0 1 1-3.5 6L5 21H3v-2l6.5-6.5A4 4 0 0 1 15 9zM16 8v.01",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  plus: "M12 5v14M5 12h14",
  speaker: "M4 9h4l5-4v14l-5-4H4zM16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11",
};

export function Icon({ name }: { name: string }) {
  return (
    <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"
         stroke-linecap="round" stroke-linejoin="round">
      <path d={PATHS[name] ?? ""} />
    </svg>
  );
}

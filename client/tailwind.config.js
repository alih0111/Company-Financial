/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class", // <-- add this line to enable class-based dark mode
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};

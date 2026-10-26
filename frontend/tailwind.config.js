/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        ink: {
          50: "#f2f3fb",
          100: "#e6e8f6",
          200: "#cdd2ed",
          500: "#7165ce",
          600: "#5e52b9",
          700: "#4d439b",
          900: "#17172d",
        },
      },
      boxShadow: {
        card: "0 2px 12px rgba(22, 27, 45, .045)",
      },
    },
  },
  plugins: [],
};

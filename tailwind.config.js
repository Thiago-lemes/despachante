module.exports = {
  content: [
    './webapp/documentos/templates/**/*.html',
    './webapp/documentos/forms.py',
    './webapp/documentos/static/documentos/app.js'
  ],
  theme: {
    extend: {
      colors: {
        ink: '#101820',
        paper: '#f4f6f5',
        steel: '#dbe1df',
        kingdom: '#18a34a',
        gold: '#c79a35',
        violet: '#65428f'
      },
      fontFamily: {
        display: ['Trebuchet MS', 'Segoe UI', 'sans-serif'],
        sans: ['Segoe UI', 'Arial', 'sans-serif'],
        data: ['ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace']
      },
      boxShadow: {
        panel: '0 1px 2px rgba(16,24,32,.06), 0 10px 28px rgba(16,24,32,.06)'
      }
    }
  },
  plugins: []
}

// Applies the persisted theme before first paint (external file to satisfy the CSP: no inline scripts).
// Light is the default; only an explicit saved "dark" preference switches to the dark theme.
;(function () {
  var root = document.documentElement
  try {
    var raw = window.localStorage.getItem('bf-ui-prefs')
    var theme = raw ? (JSON.parse(raw).state || {}).theme : null
    if (theme === 'dark') {
      root.classList.add('dark')
      root.style.colorScheme = 'dark'
    } else {
      root.classList.remove('dark')
      root.style.colorScheme = 'light'
    }
  } catch (e) {
    root.classList.remove('dark')
  }
})()

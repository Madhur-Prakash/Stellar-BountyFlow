import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './index.css'

import App from './App'
import { installAuthFailureHandler } from './lib/query-client'
import { applyTheme, useUiPrefs } from './stores/ui-prefs'

installAuthFailureHandler()
applyTheme(useUiPrefs.getState().theme)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

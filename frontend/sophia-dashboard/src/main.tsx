import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { configureAmplify } from './config/amplify'
import { useAuthStore } from './store/authStore'
import './styles/index.css'

// Configure Amplify before rendering
configureAmplify()

// Initialize auth state
useAuthStore.getState().initialize()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

import { create } from 'zustand'
import {
  signIn,
  signOut,
  signUp,
  confirmSignUp,
  getCurrentUser,
  fetchAuthSession,
  type SignInInput,
  type SignUpInput,
  type ConfirmSignUpInput,
} from 'aws-amplify/auth'
import { isAuthConfigured } from '../config/amplify'

export interface AuthUser {
  userId: string
  email: string | undefined
  username: string
}

interface AuthState {
  // State
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean
  isAuthEnabled: boolean
  error: string | null

  // Actions
  initialize: () => Promise<void>
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  register: (email: string, password: string) => Promise<{ requiresConfirmation: boolean }>
  confirmRegistration: (email: string, code: string) => Promise<void>
  getIdToken: () => Promise<string | null>
  clearError: () => void
}

export const useAuthStore = create<AuthState>((set, get) => ({
  // Initial state
  user: null,
  isAuthenticated: false,
  isLoading: true,
  isAuthEnabled: isAuthConfigured(),
  error: null,

  // Initialize auth state from existing session
  initialize: async () => {
    const isEnabled = isAuthConfigured()
    set({ isAuthEnabled: isEnabled })

    // If auth is not configured, skip initialization
    if (!isEnabled) {
      set({
        isLoading: false,
        isAuthenticated: true, // Allow access when auth is disabled
        user: {
          userId: 'dev-user',
          email: 'dev@example.com',
          username: 'developer',
        },
      })
      return
    }

    try {
      const { userId, username, signInDetails } = await getCurrentUser()
      const session = await fetchAuthSession()
      const idToken = session.tokens?.idToken

      set({
        user: {
          userId,
          email: signInDetails?.loginId || idToken?.payload?.email as string,
          username,
        },
        isAuthenticated: true,
        isLoading: false,
        error: null,
      })
    } catch {
      // No authenticated session
      set({
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: null,
      })
    }
  },

  // Login with email and password
  login: async (email: string, password: string) => {
    set({ isLoading: true, error: null })

    try {
      const input: SignInInput = {
        username: email,
        password,
      }

      const { isSignedIn, nextStep } = await signIn(input)

      if (isSignedIn) {
        const { userId, username, signInDetails } = await getCurrentUser()
        set({
          user: {
            userId,
            email: signInDetails?.loginId || email,
            username,
          },
          isAuthenticated: true,
          isLoading: false,
        })
      } else {
        // Handle additional steps (MFA, etc.)
        set({
          isLoading: false,
          error: `Additional authentication step required: ${nextStep.signInStep}`,
        })
      }
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : 'Login failed',
      })
      throw err
    }
  },

  // Logout
  logout: async () => {
    set({ isLoading: true })

    try {
      await signOut()
      set({
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: null,
      })
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : 'Logout failed',
      })
    }
  },

  // Register new account
  register: async (email: string, password: string) => {
    set({ isLoading: true, error: null })

    try {
      const input: SignUpInput = {
        username: email,
        password,
        options: {
          userAttributes: {
            email,
          },
        },
      }

      const { isSignUpComplete, nextStep } = await signUp(input)

      set({ isLoading: false })

      return {
        requiresConfirmation: !isSignUpComplete && nextStep.signUpStep === 'CONFIRM_SIGN_UP',
      }
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : 'Registration failed',
      })
      throw err
    }
  },

  // Confirm registration with verification code
  confirmRegistration: async (email: string, code: string) => {
    set({ isLoading: true, error: null })

    try {
      const input: ConfirmSignUpInput = {
        username: email,
        confirmationCode: code,
      }

      await confirmSignUp(input)
      set({ isLoading: false })
    } catch (err) {
      set({
        isLoading: false,
        error: err instanceof Error ? err.message : 'Confirmation failed',
      })
      throw err
    }
  },

  // Get JWT ID token for API calls
  getIdToken: async () => {
    const { isAuthEnabled } = get()

    // Return null if auth is disabled (backend will accept without token)
    if (!isAuthEnabled) {
      return null
    }

    try {
      const session = await fetchAuthSession()
      return session.tokens?.idToken?.toString() || null
    } catch {
      return null
    }
  },

  // Clear error
  clearError: () => set({ error: null }),
}))

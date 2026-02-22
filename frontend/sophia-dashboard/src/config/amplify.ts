import { Amplify } from 'aws-amplify'

// Amplify configuration for AWS Cognito
// These values should be set via environment variables in production

const amplifyConfig = {
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID || '',
      userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID || '',
      loginWith: {
        email: true,
        username: false,
      },
    },
  },
}

export function configureAmplify() {
  const { userPoolId, userPoolClientId } = amplifyConfig.Auth.Cognito

  // Only configure if Cognito settings are provided
  if (userPoolId && userPoolClientId) {
    Amplify.configure(amplifyConfig)
    return true
  }

  console.warn(
    'Cognito configuration not found. Auth is disabled. ' +
      'Set VITE_COGNITO_USER_POOL_ID and VITE_COGNITO_CLIENT_ID environment variables.'
  )
  return false
}

export function isAuthConfigured(): boolean {
  return Boolean(
    import.meta.env.VITE_COGNITO_USER_POOL_ID &&
      import.meta.env.VITE_COGNITO_CLIENT_ID
  )
}

export default amplifyConfig

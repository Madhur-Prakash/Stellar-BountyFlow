import { Navigate, useLocation } from 'react-router'

/** The guide used to live at /docs: redirects /docs#section to /guide#section so old links keep working. */
export function LegacyGuideRedirect() {
  const { hash } = useLocation()
  return <Navigate to={{ pathname: '/guide', hash }} replace />
}

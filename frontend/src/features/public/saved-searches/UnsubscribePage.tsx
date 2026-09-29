import { BellOff, CircleAlert, LoaderCircle } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'

import { PageContainer } from '@/components/layout/PageContainer'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { errorMessage, isApiError } from '@/lib/api/client'
import { useUnsubscribeSavedSearch } from '@/lib/api/queries/discovery'

/**
 * Landing page of the unsubscribe link in saved-search alert emails. Alerts only stop after the confirm button
 * (link scanners that open the page do not unsubscribe anyone), and no sign-in is needed: the signed token in the
 * link is the authorisation.
 */
export default function UnsubscribePage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const unsubscribe = useUnsubscribeSavedSearch()
  const done = unsubscribe.data
  const invalid =
    !token ||
    (unsubscribe.isError && isApiError(unsubscribe.error) && [404, 422].includes(unsubscribe.error.status))

  return (
    <PageContainer className="flex min-h-[60vh] items-center justify-center py-16">
      <Card className="w-full max-w-md">
        {invalid ? (
          <>
            <CardHeader>
              <CircleAlert className="mb-2 size-5 text-muted-foreground" aria-hidden />
              <CardTitle>
                <h1 className="font-display text-xl">This link does not work</h1>
              </CardTitle>
              <CardDescription>
                The saved search may have been deleted, or the link was cut short. You can manage alerts from
                your saved searches.
              </CardDescription>
            </CardHeader>
            <CardFooter>
              <Button asChild variant="outline">
                <Link to="/app/saved?tab=searches">Saved searches</Link>
              </Button>
            </CardFooter>
          </>
        ) : done ? (
          <>
            <CardHeader>
              <BellOff className="mb-2 size-5 text-muted-foreground" aria-hidden />
              <CardTitle>
                <h1 className="font-display text-xl">Alerts are off</h1>
              </CardTitle>
              <CardDescription role="status">
                You will no longer get alerts for “{done.name}”. The search itself is still saved.
              </CardDescription>
            </CardHeader>
            <CardFooter>
              <Button asChild variant="outline">
                <Link to="/app/saved?tab=searches">Manage saved searches</Link>
              </Button>
            </CardFooter>
          </>
        ) : (
          <>
            <CardHeader>
              <BellOff className="mb-2 size-5 text-muted-foreground" aria-hidden />
              <CardTitle>
                <h1 className="font-display text-xl">Stop alerts for this saved search?</h1>
              </CardTitle>
              <CardDescription>
                Email and in-app alerts stop. The search stays saved and you can turn alerts back on later.
              </CardDescription>
            </CardHeader>
            {unsubscribe.isError && (
              <CardContent>
                <p role="alert" className="text-sm text-destructive">
                  {errorMessage(unsubscribe.error)}
                </p>
              </CardContent>
            )}
            <CardFooter className="gap-2">
              <Button disabled={unsubscribe.isPending} onClick={() => unsubscribe.mutate(token)}>
                {unsubscribe.isPending && <LoaderCircle className="animate-spin" />}
                Stop alerts
              </Button>
              <Button asChild variant="ghost">
                <Link to="/bounties">Keep them</Link>
              </Button>
            </CardFooter>
          </>
        )}
      </Card>
    </PageContainer>
  )
}

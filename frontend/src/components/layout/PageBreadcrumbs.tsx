import { Fragment } from 'react'
import { Link } from 'react-router'

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { cn } from '@/lib/utils'

export type Crumb = { label: string; to?: string }

/**
 * The trail above a page title. The last crumb is the current page and is never a link.
 *
 * Public pages use it as their way back: arriving on the marketplace or a profile from a link leaves no other
 * route to where you came from, since the site header only offers top-level destinations.
 */
export function PageBreadcrumbs({ items, className }: { items: Crumb[]; className?: string }) {
  if (items.length === 0) return null
  return (
    <Breadcrumb className={className}>
      <BreadcrumbList className="text-[0.8125rem]">
        {items.map((c, i) => (
          <Fragment key={`${c.label}-${i}`}>
            <BreadcrumbItem>
              {c.to && i < items.length - 1 ? (
                <BreadcrumbLink asChild>
                  <Link to={c.to}>{c.label}</Link>
                </BreadcrumbLink>
              ) : (
                <BreadcrumbPage className={cn('truncate', items.length > 1 && 'max-w-[40ch]')}>
                  {c.label}
                </BreadcrumbPage>
              )}
            </BreadcrumbItem>
            {i < items.length - 1 && <BreadcrumbSeparator />}
          </Fragment>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  )
}

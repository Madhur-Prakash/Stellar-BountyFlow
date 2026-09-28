import type { ReactNode } from 'react'
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

const SIZES = {
  /** Workspace and admin pages: Geist 500, 28–32px. */
  default: {
    title: 'text-[1.75rem] leading-[1.1] tracking-[-0.035em] md:text-[2rem]',
    description: 'mt-2 text-[0.9375rem]',
    actions: '',
  },
  /** Public pages: a larger, light headline (Geist 400, up to 48px); the actions keep their size beside it. */
  display: {
    title: 'text-[2.125rem] leading-[1.05] font-normal tracking-[-0.035em] md:text-[2.5rem] xl:text-[3rem]',
    description: 'mt-3 text-[0.9375rem] md:text-base',
    actions: 'md:shrink-0',
  },
} as const

/**
 * A page's title row: optional breadcrumbs, an optional small mono label (`eyebrow`), the h1 in Geist with tight
 * tracking, a short description, and actions on the right. `size="display"` is the larger, lighter public-page
 * headline.
 */
export function PageHeader({
  title,
  description,
  actions,
  breadcrumbs,
  eyebrow,
  size = 'default',
  className,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  breadcrumbs?: Crumb[]
  eyebrow?: ReactNode
  size?: keyof typeof SIZES
  className?: string
}) {
  const s = SIZES[size]
  return (
    <header className={cn('flex flex-col gap-3 pb-6 lg:pb-7', className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <Breadcrumb>
          <BreadcrumbList className="text-[0.8125rem]">
            {breadcrumbs.map((c, i) => (
              <Fragment key={`${c.label}-${i}`}>
                <BreadcrumbItem>
                  {c.to && i < breadcrumbs.length - 1 ? (
                    <BreadcrumbLink asChild>
                      <Link to={c.to}>{c.label}</Link>
                    </BreadcrumbLink>
                  ) : (
                    <BreadcrumbPage className="max-w-[40ch] truncate">{c.label}</BreadcrumbPage>
                  )}
                </BreadcrumbItem>
                {i < breadcrumbs.length - 1 && <BreadcrumbSeparator />}
              </Fragment>
            ))}
          </BreadcrumbList>
        </Breadcrumb>
      )}
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          {eyebrow && <div className="label-mono mb-2">{eyebrow}</div>}
          <h1 className={cn('font-display', s.title)}>{title}</h1>
          {description && (
            <p className={cn('max-w-2xl leading-relaxed text-muted-foreground', s.description)}>
              {description}
            </p>
          )}
        </div>
        {actions && <div className={cn('flex flex-wrap items-center gap-2', s.actions)}>{actions}</div>}
      </div>
    </header>
  )
}

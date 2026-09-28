import type { UseQueryResult } from '@tanstack/react-query'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Users } from 'lucide-react'
import { Link } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import type { Page } from '@/lib/api/types'
import { renderWithProviders } from '@/test/render'

import { AdminTable, PagedResults, type AdminColumn } from './admin-shared'

type Row = { id: string; name: string }

const rows: Row[] = [
  { id: 'a', name: 'First entry' },
  { id: 'b', name: 'Second entry' },
]

const columns: AdminColumn<Row>[] = [
  { key: 'name', header: 'Name', mobile: 'title', cell: (r) => <Link to={`/x/${r.id}`}>{r.name}</Link> },
  { key: 'id', header: 'Id', cell: (r) => r.id },
]

/** A settled page query, shaped like the fields PagedResults reads. */
function pageQuery(page: Partial<Page<Row>>): UseQueryResult<Page<Row>> {
  const data: Page<Row> = { items: [], total: 0, page: 1, page_size: 20, pages: 0, ...page }
  return {
    data,
    error: null,
    isError: false,
    isPending: false,
    isFetching: false,
    isPlaceholderData: false,
    refetch: vi.fn(),
  } as unknown as UseQueryResult<Page<Row>>
}

describe('AdminTable', () => {
  it('renders a captioned table and stacked rows', () => {
    renderWithProviders(<AdminTable rows={rows} columns={columns} getKey={(r) => r.id} caption="Entries" />)
    const table = screen.getByRole('table', { name: 'Entries' })
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    expect(screen.getByRole('list', { name: 'Entries' })).toBeInTheDocument()
  })

  it('expands a row from its button or a click on the row, but not from a link inside it', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <AdminTable
        rows={rows}
        columns={columns}
        getKey={(r) => r.id}
        caption="Entries"
        detail={(r) => <p>Detail for {r.name}</p>}
        detailLabel={(r) => `Show details for ${r.name}`}
      />,
    )
    const table = screen.getByRole('table', { name: 'Entries' })
    const toggle = within(table).getByRole('button', { name: 'Show details for First entry' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(within(table).getByText('Detail for First entry')).toBeInTheDocument()

    await user.click(toggle)
    expect(within(table).queryByText('Detail for First entry')).not.toBeInTheDocument()

    await user.click(within(table).getByRole('cell', { name: 'b' }))
    expect(within(table).getByText('Detail for Second entry')).toBeInTheDocument()

    await user.click(within(table).getByRole('link', { name: 'First entry' }))
    expect(within(table).queryByText('Detail for First entry')).not.toBeInTheDocument()
  })
})

describe('PagedResults', () => {
  const base = {
    label: 'Entries',
    itemLabel: 'entries',
    errorTitle: 'Could not load entries',
    empty: { icon: Users, title: 'No entries yet' },
    skeleton: 'admin-test-list',
    onPageChange: () => {},
  }

  it('shows the toolbar, the count and the rows, without a footer on a single page', () => {
    renderWithProviders(
      <PagedResults
        {...base}
        query={pageQuery({ items: rows, total: 2, pages: 1 })}
        toolbar={<input aria-label="Search entries" />}
      >
        {(items) => <AdminTable rows={items} columns={columns} getKey={(r) => r.id} caption="Entries" />}
      </PagedResults>,
    )
    expect(within(screen.getByRole('search')).getByLabelText('Search entries')).toBeInTheDocument()
    expect(screen.getByText('2 entries')).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Entries' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Pagination' })).not.toBeInTheDocument()
  })

  it('puts pagination in the footer when there is more than one page', () => {
    renderWithProviders(
      <PagedResults {...base} query={pageQuery({ items: rows, total: 42, pages: 3 })}>
        {(items) => <AdminTable rows={items} columns={columns} getKey={(r) => r.id} caption="Entries" />}
      </PagedResults>,
    )
    expect(screen.getByRole('navigation', { name: 'Pagination' })).toBeInTheDocument()
  })

  it('shows the empty state, and a clear-filters action when filtered', async () => {
    const user = userEvent.setup()
    const onClearFilters = vi.fn()
    const { unmount } = renderWithProviders(
      <PagedResults {...base} query={pageQuery({})}>
        {() => null}
      </PagedResults>,
    )
    expect(screen.getByRole('heading', { name: 'No entries yet' })).toBeInTheDocument()
    unmount()

    renderWithProviders(
      <PagedResults {...base} query={pageQuery({})} filtered onClearFilters={onClearFilters}>
        {() => null}
      </PagedResults>,
    )
    expect(screen.getByRole('heading', { name: 'No entries match these filters' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(onClearFilters).toHaveBeenCalledOnce()
  })
})

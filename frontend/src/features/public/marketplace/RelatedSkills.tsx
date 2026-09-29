import { Link } from 'react-router'

import { Bones } from '@/components/layout/Bones'
import { Skeleton } from '@/components/ui/skeleton'
import { useRelatedSkills } from '@/lib/api/queries/discovery'

const TAG =
  'inline-flex h-7 items-center rounded-[4px] border bg-surface/60 px-2 text-xs text-muted-foreground transition-colors max-lg:h-10 max-lg:px-3'

function RelatedSkillsFallback() {
  return (
    <div className="flex flex-wrap gap-1.5" role="status" aria-label="Loading related skills">
      {[16, 20, 14, 18].map((w) => (
        <Skeleton key={w} className="h-7 rounded-[4px]" style={{ width: `${w * 0.25}rem` }} />
      ))}
    </div>
  )
}

/**
 * Skills that often go with these ones (from the skill graph). Each links to the marketplace filtered by it when
 * bounties require it; skills only used as tags are shown without a link.
 */
export function RelatedSkills({ skills }: { skills: string[] }) {
  const { data, isPending, isError } = useRelatedSkills(skills)
  if (isError || (!isPending && (!data || data.related.length === 0))) return null
  return (
    <div className="mt-5">
      <h3 id="related-skills-h" className="mb-2 text-[0.8125rem] font-medium text-muted-foreground">
        Related skills
      </h3>
      <Bones name="bounty-related-skills" loading={isPending} fallback={<RelatedSkillsFallback />}>
        {data && (
          <ul className="flex flex-wrap gap-1.5" aria-labelledby="related-skills-h">
            {data.related.map((r) => (
              <li key={r.skill}>
                {r.marketplace_skills.length ? (
                  <Link
                    to={`/bounties?skills=${encodeURIComponent(r.marketplace_skills.join(','))}`}
                    className={`${TAG} hover:border-foreground/25 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none`}
                    title={`Often asked for with ${r.via.join(', ')}`}
                  >
                    {r.skill}
                  </Link>
                ) : (
                  <span className={TAG} title={`Often asked for with ${r.via.join(', ')}`}>
                    {r.skill}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Bones>
    </div>
  )
}

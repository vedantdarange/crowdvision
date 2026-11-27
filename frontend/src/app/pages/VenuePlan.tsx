import { Link } from 'react-router';
import { ArrowUpRight, Compass } from 'lucide-react';
// An illustrative venue diagram. Labels link to existing zone preview routes.
export function VenuePlan() {
  return (
    <div className="venue-plan">
      <svg
        viewBox="0 0 640 265"
        preserveAspectRatio="xMidYMid slice"
        aria-hidden="true"
      >
        <defs>
          <pattern
            id="blocks"
            width="116"
            height="82"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(-18)"
          >
            <rect width="116" height="82" fill="#f3efeb" />
            <rect x="4" y="4" width="69" height="48" rx="3" fill="#e1dbd7" />
            <rect x="78" y="4" width="33" height="48" rx="3" fill="#e8dfd9" />
            <rect x="4" y="57" width="107" height="20" rx="3" fill="#e3dbd5" />
          </pattern>
        </defs>
        <rect width="640" height="265" fill="url(#blocks)" />
        <path
          d="M-20 58 Q130 26 218 62 T496 34 L660 10"
          fill="none"
          stroke="#cdd2d6"
          strokeWidth="30"
        />
        <path
          d="M-10 247 L160 184 L267 118 L430 99 L662 19 M136 -23 L225 80 L347 165 L432 290"
          fill="none"
          stroke="#fffaf6"
          strokeWidth="13"
        />
        <path
          d="M186 94 L329 53 L499 111 L436 207 L292 230 L193 171Z"
          fill="#dec3b0"
          stroke="#fff7f0"
          strokeWidth="5"
        />
        <path
          d="M201 100 L329 65 L478 114 L427 195 L295 217 L205 165Z"
          fill="none"
          stroke="#9b7964"
          strokeDasharray="5 5"
        />
        <path
          d="M216 157 Q276 138 315 161 T449 138"
          stroke="#f8e9dc"
          strokeWidth="6"
          fill="none"
        />
      </svg>
      <span className="plan-compass">
        <Compass size={16} /> N
      </span>
      {(['Main Gate', 'Stage Area', 'Exit Lane'] as const).map((label, i) => (
        <Link className={`map-pin pin-${i}`} to={`/zones/${i + 1}`} key={label}>
          <i />
          {label}
          <ArrowUpRight size={11} />
        </Link>
      ))}
      <span className="plan-credit">Illustrative venue plan</span>
    </div>
  );
}

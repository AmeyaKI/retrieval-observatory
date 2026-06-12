// Fixed difficulty ramp reused identically across Forge and TraceLens so a color
// never means two things. easy → extreme = green → amber → orange → red.
export const DIFFICULTY_ORDER = ['easy', 'medium', 'hard', 'extreme'] as const
export type Difficulty = (typeof DIFFICULTY_ORDER)[number]

export function difficultyChipClass(label: string): string {
  switch (label) {
    case 'easy':
      return 'bg-green-100 text-green-800 border-green-200'
    case 'medium':
      return 'bg-amber-100 text-amber-800 border-amber-200'
    case 'hard':
      return 'bg-orange-100 text-orange-800 border-orange-200'
    case 'extreme':
      return 'bg-red-100 text-red-800 border-red-200'
    default:
      return 'bg-gray-100 text-gray-700 border-gray-200'
  }
}

export function difficultyBarColor(label: string): string {
  switch (label) {
    case 'easy':
      return '#22c55e'
    case 'medium':
      return '#f59e0b'
    case 'hard':
      return '#f97316'
    case 'extreme':
      return '#ef4444'
    default:
      return '#9ca3af'
  }
}

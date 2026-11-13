export function shouldShowSeedBanner(seedLoaded: boolean | null): boolean {
  return seedLoaded === false;
}
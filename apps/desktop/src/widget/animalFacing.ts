export type AnimalFacing = "front" | "left" | "right";

export function animalFacingForDelta(dx: number, threshold = 12): AnimalFacing {
  if (dx < -threshold) return "left";
  if (dx > threshold) return "right";
  return "front";
}

export function animalYawForFacing(facing: AnimalFacing): number {
  if (facing === "left") return -Math.PI / 2;
  if (facing === "right") return Math.PI / 2;
  return 0;
}

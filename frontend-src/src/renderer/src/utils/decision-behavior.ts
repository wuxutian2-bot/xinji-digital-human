/** Bounded, procedural controls for models with standard Cubism parameters. */
export class DecisionBehavior {
  private startedAt: number | null = null;
  private gaze: 'attentive' | 'soft' | null = null;

  start(motion: unknown, gaze: unknown, now: number): void {
    this.startedAt = motion === 'gentle_nod' ? now : null;
    this.gaze = gaze === 'attentive' || gaze === 'soft' ? gaze : null;
  }

  clear(): void {
    this.startedAt = null;
    this.gaze = null;
  }

  sample(now: number): { angleY: number; eyeX: number | null; eyeY: number | null } {
    const elapsed = this.startedAt === null ? -1 : now - this.startedAt;
    // One small nod over 1.2 seconds; zero offset at both ends.
    const angleY = elapsed > 0 && elapsed < 1200
      ? -8 * Math.sin(Math.PI * elapsed / 1200) ** 2 : 0;
    return {
      angleY,
      eyeX: this.gaze === null ? null : 0,
      eyeY: this.gaze === null ? null : this.gaze === 'soft' ? -0.15 : 0,
    };
  }
}

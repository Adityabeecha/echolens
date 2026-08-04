---
name: EchoLens Evidence Docket
description: An inspectable feedback-forensics workspace that carries customer signals through investigation to verified fixes.
colors:
  vermilion: "#c53e33"
  vermilion-hover: "#a62f27"
  cobalt-reference: "#245da8"
  verified-green: "#287343"
  mineral-paper: "#f3f0e9"
  docket-paper: "#fbfaf7"
  graphite: "#202528"
  graphite-soft: "#42484a"
  rule: "#cdc6ba"
typography:
  display:
    fontFamily: "Fraunces, Georgia, serif"
    fontSize: "44px"
    fontWeight: 700
    lineHeight: 1.25
  headline:
    fontFamily: "Fraunces, Georgia, serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.25
  body:
    fontFamily: "IBM Plex Sans, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "11px"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "0.08em"
rounded:
  mark: "4px"
  control: "5px"
  card: "8px"
  overlay: "12px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.vermilion}"
    textColor: "{colors.docket-paper}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  button-secondary:
    backgroundColor: "{colors.docket-paper}"
    textColor: "{colors.graphite}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "9px 14px"
  case-card:
    backgroundColor: "{colors.docket-paper}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.card}"
    padding: "12px"
---

# Design System: EchoLens Evidence Docket

## Overview

**Creative North Star: "The Evidence Docket"**

EchoLens should feel like a precise working file on an investigator's desk: calm, tactile, and dense with proof without becoming crowded. Mineral paper, ruled registers, docket numbers, and restrained stamps make the work inspectable; graphite navigation provides a stable operational frame.

The interface rejects the generic analytics-dashboard look. Hierarchy comes from typography, rules, numbering, and evidence state—not decorative gradients or a mosaic of interchangeable cards.

**Key Characteristics:**

- Paper-and-ink materiality with a dark graphite shell.
- Vermilion marks decisive actions and live evidence; cobalt marks references.
- Compact, explicit workflow states from signal through verified fix.
- Editorial headings paired with highly legible operational copy.

## Colors

The palette behaves like a printed case file: warm neutrals carry content, graphite carries structure, and accents remain scarce and semantic.

### Primary

- **Docket Vermilion:** Reserved for primary actions, active evidence marks, and focus.

### Secondary

- **Reference Cobalt:** Used for links, citations, and information that points outward.
- **Verified Green:** Used only for confirmed outcomes and successful checks.

### Neutral

- **Mineral Paper:** The application canvas and texture ground.
- **Docket Paper:** Raised working surfaces and registers.
- **Graphite:** Primary text and the navigation shell.
- **Rule:** Dividers, field edges, and table structure.

**The Red-Pencil Rule.** Vermilion is a scarce annotation color, not a general decoration.

## Typography

**Display Font:** Fraunces (with Georgia fallback)<br>
**Body Font:** IBM Plex Sans (with system sans-serif fallback)<br>
**Label/Mono Font:** IBM Plex Mono

**Character:** Fraunces gives findings editorial authority; Plex keeps investigation metadata, controls, and long-form evidence neutral and precise.

### Hierarchy

- **Display:** Reserved for high-signal scores and rare opening statements.
- **Headline:** Screen and section titles with editorial weight.
- **Title:** Case names and actionable findings.
- **Body:** Default reading voice; keep explanatory passages comfortably short.
- **Label:** Uppercase docket metadata, counters, stages, and timestamps.

**The Two-Voice Rule.** Fraunces names the evidence; Plex operates on it.

## Layout

Desktop uses a fixed graphite sidebar (248px), a workflow rail, and a content measure up to 1180px. The Today view prioritizes a two-column briefing desk: decision-ready intake on the left, running work on the right, and verified outcomes immediately below. Lists use registers with actions at row ends.

At 900px gutters tighten. On phone widths, navigation becomes a horizontally scrollable top rail, columns stack, and workflow stages remain reachable without truncating their meaning. The 4px spacing base scales through 8, 12, 16, 24, and 32px.

## Elevation & Depth

The system is flat by default. Paper tint, 1px rules, and the graphite shell establish depth; small warm shadows appear only where a control or overlay needs separation.

**The Filed-Flat Rule.** A resting register is outlined, not floating.

## Shapes

Corners are gently mechanical: controls use 5px, cards 8px, overlays 12px, and status pills use a full radius. One-pixel vermilion evidence marks and square docket-number blocks keep the silhouette disciplined.

## Components

### Buttons

- **Shape:** Compact control corners (5px) with clear borders.
- **Primary:** Vermilion fill, light text, and a restrained warm shadow.
- **Hover / Focus:** Darken on hover; use a 2px vermilion focus outline with 2px offset.
- **Secondary / Ghost:** Paper or transparent surfaces with graphite text and visible rule-colored edges.

### Chips

- **Style:** Small bordered pills with semantic tint; use them for status, never as decoration.
- **State:** Active filters may use a filled neutral paper state; lifecycle status keeps its semantic color.

### Cards / Containers

- **Corner Style:** Gentle docket corners (8px).
- **Background:** Docket paper over mineral paper.
- **Shadow Strategy:** Flat at rest.
- **Border:** A visible 1px rule; live evidence may carry a 1px vermilion mark.
- **Internal Padding:** 12-24px according to density.

### Inputs / Fields

- **Style:** Paper fill, graphite copy, rule-colored 1px stroke, and 5px corners.
- **Focus:** Vermilion outline; never rely on color change alone.
- **Error / Disabled:** Preserve readable contrast and explain the state in text.

### Navigation

Graphite navigation uses compact Plex labels, a clear active register, and vermilion evidence marks. On mobile it becomes a horizontal top rail rather than disappearing behind an icon-only menu.

### Workflow Rail

Four numbered stages—Signal, Investigation, Finding, Fix—make progress persistent across operational screens. Active and completed stages must remain distinguishable without hiding later stages.

### Case Register

Every case carries a stable docket number, lifecycle status, age or iteration metadata, a one-line explanation, and one explicit next action. Title navigation and the row action are separate controls.

## Do's and Don'ts

### Do:

- **Do** keep the signal-to-fix chain visible and use provenance beside claims.
- **Do** use vermilion for decisive action, focus, and evidence marks.
- **Do** place row actions at the trailing edge and label them with outcomes.
- **Do** preserve keyboard focus, contrast, and readable workflow labels at every breakpoint.

### Don't:

- **Don't** turn the interface into a generic grid of disconnected metric cards.
- **Don't** add gradients, glass effects, oversized radii, or ornamental shadows.
- **Don't** use color as the only carrier of state.
- **Don't** hide operational navigation or lifecycle context on mobile.

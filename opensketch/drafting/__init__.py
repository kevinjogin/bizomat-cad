"""BIZOMAT Drafting Intelligence Engine.

The reasoning layer between the AI assistant and the existing SOLIDWORKS tools. It never talks to SOLIDWORKS
itself: the sw_drafting_* tools (opensketch/sw_drafting.py) read the model and the drawing through the existing
commands (read, geometry, read_drawing) and make drawings through the existing ones (create_drawing,
edit_drawing, export). Everything here is plain data in and plain data out, so the same intelligence serves every
connected AI model.

Modules (docs/drafting-intelligence/TECHNICAL_SPECIFICATION.md):
  facts          A  geometry facts from the solid (runs in the CAD worker: OpenCascade)
  features       A  engineering features recognised from the facts (holes, patterns, shafts, steps, fillets...)
  understanding  A  the engineering model: geometry + SOLIDWORKS design information, confirmed / inferred / unknown
  disciplines    B  multi-label drafting discipline classification with reasons
  reasoning      C  discipline modules: machining, turning, weldment, structural, sheet metal, assembly, piping, GA
  knowledge      D  the drafting knowledge base: structured entries, retrieval, sources, validation status
  strategy       E  the drawing plan: purpose, package, sheet, scale, views, sections, details, notes, questions
  dimensioning   F  dimension planning and checks (coverage, duplicates, redundancy, datums, callouts)
  standards      G  standards profiles (AS 1100, ISO, ASME): projection, notes, symbols, title block fields
  layout         H  layout evaluation of a real drawing and non-critical corrections (view moves)
  qa             I  the drawing quality report: 100-point index and separate release blockers
  learning       J  plans, feedback, approved examples and benchmark evaluation (SQLite in the data folder)
  benchmarks     J  synthetic, clearly labelled benchmark models with expected results
"""

ENGINE_VERSION = "0.1.0"

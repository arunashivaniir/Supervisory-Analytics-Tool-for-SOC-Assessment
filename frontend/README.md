# Interface

The React interface. It is a presentation layer: every value it shows comes from
`SATSAPipeline` through the local adapter in `../backend`, and it computes no
scores, counts or conclusions of its own.

## Running it

    npm install

    npm run dev        # development server, proxying /api to 127.0.0.1:8000
    npm run build      # typecheck and build into dist/
    npm run lint

The adapter has to be running for either one. From the repository root:

    python launcher.py --dev     # adapter and interface together
    python launcher.py           # adapter serving the built interface

## Checking it

    npm run check

Drives a real browser against the running interface and the running adapter,
and compares what each screen shows with the pipeline result the adapter
returned. It reads its expectations from that result, so it is meaningful for
evidence that produced findings and evidence that produced none.

## Layout

    src/app/          shared analysis state, selectors, application frame
    src/components/   layout, interface primitives, per-feature components
    src/lib/          status vocabulary, formatting, class names
    src/pages/        Overview, Assessments, assessment detail, Findings,
                      Evidence, Reports
    src/services/     the adapter's HTTP surface
    src/types/        TypeScript mirrors of the pipeline result

The TypeScript interfaces in `src/types/pipeline.ts` describe the backend. They
do not extend it, and they do not add fields the pipeline does not produce. A
field that can be absent is typed as absent rather than defaulted, because a
fabricated default is a value the pipeline never reported.

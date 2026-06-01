const DASH = "#/dashboard";

function Step({ n, title, body }) {
  return (
    <div className="relative rounded-xl border border-gray-200 bg-white p-6">
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-900 font-mono text-sm font-bold text-white">
        {n}
      </div>
      <h3 className="mt-4 text-base font-semibold text-gray-900">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-gray-600">{body}</p>
    </div>
  );
}

function Feature({ title, body }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6">
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-gray-600">{body}</p>
    </div>
  );
}

function Faq({ q, a }) {
  return (
    <details className="group border-b border-gray-200 py-4">
      <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold text-gray-900">
        {q}
        <span className="ml-4 text-gray-400 transition-transform group-open:rotate-45">+</span>
      </summary>
      <p className="mt-3 text-sm leading-relaxed text-gray-600">{a}</p>
    </details>
  );
}

export default function Landing() {
  return (
    <div className="min-h-screen bg-white text-gray-900">
      {/* Nav */}
      <header className="sticky top-0 z-30 border-b border-gray-100 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <a href="#/" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-gray-900 font-bold text-white">
              FV
            </div>
            <span className="text-sm font-semibold tracking-tight">FreightVoice</span>
          </a>
          <nav className="hidden items-center gap-8 text-sm text-gray-600 md:flex">
            <a href="#problem" className="hover:text-gray-900">Problem</a>
            <a href="#how" className="hover:text-gray-900">How it works</a>
            <a href="#product" className="hover:text-gray-900">Product</a>
            <a href="#faq" className="hover:text-gray-900">FAQ</a>
          </nav>
          <a
            href="https://www.youtube.com/shorts/b9T2XrsBO7M"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-800 hover:bg-gray-50"
          >
            <svg className="h-3.5 w-3.5 text-red-400" viewBox="0 0 24 24" fill="currentColor">
              <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
            </svg>
            Watch Demo
          </a>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-6xl px-6 pt-20 pb-16 text-center">
        <span className="inline-flex items-center gap-2 rounded-full border border-orange-200 bg-orange-50 px-3 py-1 text-xs font-semibold text-orange-700">
          <span className="h-1.5 w-1.5 rounded-full bg-orange-500" />
          AI agents that make your outbound carrier calls
        </span>
        <h1 className="mx-auto mt-6 max-w-3xl text-4xl font-bold leading-[1.1] tracking-tight text-gray-900 sm:text-6xl">
          AI agents call your carriers so your line never stops.
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-gray-600">
          FreightVoice is an AI voice agent that places outbound calls to your
          carriers, drivers, and suppliers, confirming ETAs, verifying cargo,
          prepping docks, and scoring delivery risk on every inbound load. Your
          team stops dialing 80 numbers a day and just handles the exceptions.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <a
            href="https://www.youtube.com/shorts/b9T2XrsBO7M"
            target="_blank"
            rel="noopener noreferrer"
            className="w-full rounded-md border border-gray-300 bg-white px-6 py-3 text-sm font-semibold text-gray-800 hover:bg-gray-50 sm:w-auto flex items-center justify-center gap-2"
          >
            <svg className="h-4 w-4 text-red-400" viewBox="0 0 24 24" fill="currentColor">
              <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
            </svg>
            Watch Demo
          </a>
          <a
            href="#how"
            className="w-full rounded-md border border-gray-300 px-6 py-3 text-sm font-semibold text-gray-800 hover:bg-gray-50 sm:w-auto"
          >
            See how it works
          </a>
        </div>
        <p className="mt-5 text-xs text-gray-400">
          Autonomous outbound calls · Live demo dashboard · Runs on Nemotron + Twilio
        </p>
      </section>

      {/* Social proof */}
      <section className="border-y border-gray-100 bg-gray-50">
        <div className="mx-auto max-w-6xl px-6 py-8">
          <p className="text-center text-xs font-semibold uppercase tracking-widest text-gray-400">
            Built for inbound coordination across
          </p>
          <div className="mt-5 flex flex-wrap items-center justify-center gap-x-10 gap-y-3 text-sm font-semibold text-gray-500">
            <span>Automotive</span>
            <span>Aerospace</span>
            <span>Heavy Equipment</span>
            <span>Semiconductors</span>
            <span>EV &amp; Battery</span>
          </div>
        </div>
      </section>

      {/* Problem */}
      <section id="problem" className="mx-auto max-w-6xl px-6 py-20">
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-sm font-semibold uppercase tracking-wide text-orange-600">
            The problem
          </p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
            One late part can cost millions, and nobody finds out in time.
          </h2>
          <p className="mt-5 text-lg leading-relaxed text-gray-600">
            Logistics coordinators make dozens of manual check-in calls a day, yet
            the signal that matters, “this load is going to be late”, usually
            arrives too late to act on. When an inbound part misses its dock
            appointment, the assembly line stalls at up to{" "}
            <span className="font-semibold text-gray-900">$1.8M per hour</span>.
          </p>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="border-t border-gray-100 bg-gray-50">
        <div className="mx-auto max-w-6xl px-6 py-20">
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-sm font-semibold uppercase tracking-wide text-orange-600">
              How it works
            </p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
              From 80 outbound calls a day to one dashboard.
            </h2>
          </div>
          <div className="mt-12 grid gap-5 md:grid-cols-3">
            <Step
              n="1"
              title="Connect your load tenders"
              body="Inbound loads, carriers, dock appointments, and production-line dependencies flow into FreightVoice with no new system to learn."
            />
            <Step
              n="2"
              title="The AI agent places the outbound call"
              body="FreightVoice dials the driver, confirms ETA and location, verifies the load is sealed and temperature-controlled, and assigns a dock and gate in natural conversation."
            />
            <Step
              n="3"
              title="You handle only exceptions"
              body="Every call is scored for delivery risk. The team reviews a live dashboard and is alerted before a line goes down, instead of dialing all day."
            />
          </div>
        </div>
      </section>

      {/* Product / features */}
      <section id="product" className="mx-auto max-w-6xl px-6 py-20">
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm font-semibold uppercase tracking-wide text-orange-600">
            What it does
          </p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
            A coordinator that never sleeps, on every load.
          </h2>
        </div>
        <div className="mt-12 grid gap-5 md:grid-cols-3">
          <Feature
            title="Inbound parts coordination"
            body="Outbound calls to carriers confirm ETA and dock, prepare receiving, and verify shipper-specific cargo conditions on every load."
          />
          <Feature
            title="Production-line protection"
            body="Scores delivery risk on each load from driver sentiment, ETA, weather, and lane history, and alerts logistics before the line stops."
          />
          <Feature
            title="Supplier compliance calls"
            body="Multilingual outbound outreach to confirm pricing, lead times, and compliance docs when tariffs or routing change."
          />
        </div>
      </section>

      {/* Metrics */}
      <section className="border-y border-gray-100 bg-gray-900">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-8 px-6 py-14 text-center md:grid-cols-4">
          {[
            ["80→0", "manual outbound calls per coordinator, per day"],
            ["$1.8M/hr", "line-down risk surfaced early"],
            ["100%", "of inbound loads called & scored"],
            ["<2s", "voice response latency"],
          ].map(([value, label]) => (
            <div key={label}>
              <div className="font-mono text-3xl font-semibold tabular-nums text-white sm:text-4xl">
                {value}
              </div>
              <div className="mt-2 text-sm text-gray-400">{label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Testimonial */}
      <section className="mx-auto max-w-3xl px-6 py-20 text-center">
        <blockquote className="text-2xl font-medium leading-relaxed tracking-tight text-gray-900">
          “We used to find out a load was late when the line operator called us.
          Now FreightVoice tells us two hours out, with a recommended action
          already attached.”
        </blockquote>
        <figcaption className="mt-6 text-sm text-gray-500">
          Logistics Director · Tier-1 automotive supplier
        </figcaption>
      </section>

      {/* FAQ */}
      <section id="faq" className="border-t border-gray-100 bg-gray-50">
        <div className="mx-auto max-w-3xl px-6 py-20">
          <h2 className="text-center text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
            Frequently asked questions
          </h2>
          <div className="mt-10">
            <Faq
              q="Are these inbound or outbound calls?"
              a="Outbound. The AI agent places the calls to your carriers, drivers, and suppliers so they never have to call you. (The 'inbound' in inbound logistics refers to the freight arriving at your plant, not the call direction.)"
            />
            <Faq
              q="Does the AI actually place real phone calls?"
              a="Yes. FreightVoice dials carriers and drivers over Twilio, holds a natural spoken conversation, and records the outcome (ETA, cargo condition, dock assignment, and a risk score) back to your dashboard."
            />
            <Faq
              q="How is delivery risk scored?"
              a="A weighted model combines the driver's voice sentiment, ETA versus the dock appointment, lane on-time history, route weather, and how vague the ETA was, producing a 0 to 100 score and a Monitor / Warning / Critical level per load."
            />
            <Faq
              q="What happens when a load is high-risk?"
              a="FreightVoice alerts your logistics team with a recommended action (source a backup carrier, pre-stage stock, adjust the schedule) without alarming the driver. Routine on-time arrivals are handled silently."
            />
            <Faq
              q="Can it handle suppliers in other languages?"
              a="Yes. Supplier compliance calls support multilingual outreach to confirm pricing, lead times, and documentation."
            />
            <Faq
              q="How do I try it?"
              a="Click Get Started to open the live operations dashboard, pick any inbound load, and trigger a call."
            />
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="mx-auto max-w-6xl px-6 py-20 text-center">
        <h2 className="text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
          Protect your line. Stop dialing.
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-lg text-gray-600">
          Open the dashboard, trigger a call, and watch FreightVoice work an
          inbound load end to end.
        </p>
        <a
          href="https://www.youtube.com/shorts/b9T2XrsBO7M"
          target="_blank"
          rel="noopener noreferrer"
          className="mt-8 inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-7 py-3 text-sm font-semibold text-gray-800 hover:bg-gray-50"
        >
          <svg className="h-4 w-4 text-red-400" viewBox="0 0 24 24" fill="currentColor">
            <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
          </svg>
          Watch Demo
        </a>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-100">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 py-8 text-sm text-gray-400 sm:flex-row">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-gray-900 text-[11px] font-bold text-white">
              FV
            </div>
            <span>FreightVoice: predictive inbound logistics</span>
          </div>
          <div className="flex items-center gap-6">
            <a href="#problem" className="hover:text-gray-700">Problem</a>
            <a href="#how" className="hover:text-gray-700">How it works</a>
            <a href={DASH} className="hover:text-gray-700">Dashboard</a>
          </div>
        </div>
      </footer>
    </div>
  );
}

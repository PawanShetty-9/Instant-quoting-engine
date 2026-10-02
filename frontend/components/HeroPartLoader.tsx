"use client";

import dynamic from "next/dynamic";

// three.js needs the browser: load the hero only on the client, with a framed placeholder.
const HeroPart = dynamic(() => import("./HeroPart"), {
  ssr: false,
  loading: () => <div className="hero-3d" aria-hidden />,
});

export default function HeroPartLoader() {
  return <HeroPart />;
}

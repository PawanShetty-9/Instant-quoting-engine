import type { Metadata } from "next";
import AuthForm from "@/components/AuthForm";
import SiteHeader from "@/components/SiteHeader";

export const metadata: Metadata = { title: "Registrieren" };

export default function Page() {
  return (
    <>
      <SiteHeader />
      <main className="page narrow">
        <AuthForm mode="signup" />
      </main>
    </>
  );
}

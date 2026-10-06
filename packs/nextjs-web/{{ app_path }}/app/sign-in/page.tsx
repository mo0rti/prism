import { SignInForm } from "@/components/sign-in-form"

/**
 * The slice's sign-in. It signs in through the backend's local development identity and is not
 * complete authentication: replace it with your identity provider before anything ships.
 */
export default function SignInPage() {
  return (
    <section>
      <h1>Local development sign-in</h1>
      <p className="notice">
        This signs you in as a development identity for local work. It is not complete authentication, and the backend
        offers it only under its <code>local</code> profile. Replace it with your identity provider before you ship.
      </p>
      <SignInForm />
    </section>
  )
}

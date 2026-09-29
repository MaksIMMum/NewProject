import { zodResolver } from '@hookform/resolvers/zod'
import { Controller, useForm } from 'react-hook-form'
import { Link, useLocation, useNavigate } from 'react-router'
import { z } from 'zod'

import {
  AuthLayout,
  AuthNotConfigured,
  GoogleButton,
  OrDivider,
  PasswordInput,
} from '@/components/auth-layout'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { authConfigured, NeedsConfirmationError, useGoogleLogin, useLogin } from '@/lib/auth'

const loginSchema = z.object({
  email: z.email('Enter a valid email'),
  password: z.string().min(1, 'Enter your password'),
})

type LoginValues = z.infer<typeof loginSchema>

type LocationState = {
  /** Where the user was headed before being sent to the login page. */
  from?: string
  /** A message from the previous page, e.g. after confirming the email. */
  notice?: string
  email?: string
} | null

export function LoginPage() {
  const navigate = useNavigate()
  const state = useLocation().state as LocationState
  const from = state?.from ?? '/home'
  const login = useLogin()
  const googleLogin = useGoogleLogin()
  const pending = login.isPending || googleLogin.isPending
  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: state?.email ?? '', password: '' },
  })

  const onError = (error: Error) => {
    // An unverified account: finish the signup by entering the emailed code.
    if (error instanceof NeedsConfirmationError) {
      navigate('/signup', { state: { confirmEmail: error.email } })
      return
    }
    form.setError('root', { message: error.message })
  }

  const onSubmit = form.handleSubmit((values) =>
    login.mutate(values, { onSuccess: () => navigate(from, { replace: true }), onError }),
  )

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to see your meetings."
      footer={
        <>
          New here?{' '}
          <Link
            to="/signup"
            className="font-semibold text-hover underline-offset-4 hover:underline"
          >
            Create an account
          </Link>
        </>
      }
    >
      {!authConfigured && <AuthNotConfigured />}
      {state?.notice && (
        <Alert>
          <AlertDescription>{state.notice}</AlertDescription>
        </Alert>
      )}
      <GoogleButton
        disabled={pending || !authConfigured}
        pending={googleLogin.isPending}
        onClick={() => googleLogin.mutate(undefined, { onError })}
      >
        Continue with Google
      </GoogleButton>
      <OrDivider />
      <form onSubmit={onSubmit} noValidate>
        <FieldGroup className="gap-4 short:gap-3">
          <Controller
            name="email"
            control={form.control}
            render={({ field, fieldState }) => (
              <Field data-invalid={fieldState.invalid}>
                <FieldLabel htmlFor="login-email">Email</FieldLabel>
                <Input
                  id="login-email"
                  type="email"
                  autoComplete="email"
                  autoFocus
                  aria-invalid={fieldState.invalid}
                  {...field}
                />
                <FieldError errors={[fieldState.error]} />
              </Field>
            )}
          />
          <Controller
            name="password"
            control={form.control}
            render={({ field, fieldState }) => (
              <Field data-invalid={fieldState.invalid}>
                <FieldLabel htmlFor="login-password">Password</FieldLabel>
                <PasswordInput
                  id="login-password"
                  autoComplete="current-password"
                  aria-invalid={fieldState.invalid}
                  {...field}
                />
                <FieldError errors={[fieldState.error]} />
              </Field>
            )}
          />
          {form.formState.errors.root && (
            <FieldError>{form.formState.errors.root.message}</FieldError>
          )}
          <Button type="submit" className="mt-1 w-full" disabled={pending}>
            {login.isPending ? 'Signing in...' : 'Sign in'}
          </Button>
        </FieldGroup>
      </form>
    </AuthLayout>
  )
}

import { useEffect } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { Controller, useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router'
import { z } from 'zod'

import { AuthLayout, GoogleButton, OrDivider, PasswordInput } from '@/components/auth-layout'
import { Button } from '@/components/ui/button'
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { authConfigured, useGoogleLogin, useSignup } from '@/lib/auth'

const signupSchema = z
  .object({
    name: z.string().trim().min(1, 'Enter your name').max(100),
    email: z.email('Enter a valid email'),
    password: z.string().min(8, 'Use at least 8 characters'),
    confirmPassword: z.string(),
  })
  .refine((v) => v.password === v.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

type SignupValues = z.infer<typeof signupSchema>

export function SignupPage() {
  const navigate = useNavigate()

  useEffect(() => {
    if (authConfigured) {
      navigate('/login', { replace: true })
    }
  }, [navigate])

  const signup = useSignup()
  const googleLogin = useGoogleLogin()
  const pending = signup.isPending || googleLogin.isPending
  const form = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: { name: '', email: '', password: '', confirmPassword: '' },
  })

  if (authConfigured) {
    return null
  }

  const onSuccess = () => navigate('/home', { replace: true })
  const onError = (error: Error) => form.setError('root', { message: error.message })

  const onSubmit = form.handleSubmit(({ name, email, password }) =>
    signup.mutate({ name: name.trim(), email, password }, { onSuccess, onError }),
  )

  return (
    <AuthLayout
      title="Create account"
      subtitle="Plan meetings with your team."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="font-semibold text-hover underline-offset-4 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <GoogleButton
        disabled={pending}
        pending={googleLogin.isPending}
        onClick={() => googleLogin.mutate(undefined, { onSuccess, onError })}
      >
        Sign up with Google
      </GoogleButton>
      <OrDivider />
      <form onSubmit={onSubmit} noValidate>
        <FieldGroup className="gap-4 short:gap-3">
          <Controller
            name="name"
            control={form.control}
            render={({ field, fieldState }) => (
              <Field data-invalid={fieldState.invalid}>
                <FieldLabel htmlFor="signup-name">Name</FieldLabel>
                <Input
                  id="signup-name"
                  autoComplete="name"
                  autoFocus
                  aria-invalid={fieldState.invalid}
                  {...field}
                />
                <FieldError errors={[fieldState.error]} />
              </Field>
            )}
          />
          <Controller
            name="email"
            control={form.control}
            render={({ field, fieldState }) => (
              <Field data-invalid={fieldState.invalid}>
                <FieldLabel htmlFor="signup-email">Email</FieldLabel>
                <Input
                  id="signup-email"
                  type="email"
                  autoComplete="email"
                  aria-invalid={fieldState.invalid}
                  {...field}
                />
                <FieldError errors={[fieldState.error]} />
              </Field>
            )}
          />
          {/* Side by side on wider screens so the whole form fits without scrolling. */}
          <div className="grid gap-4 sm:grid-cols-2 short:gap-3">
            <Controller
              name="password"
              control={form.control}
              render={({ field, fieldState }) => (
                <Field data-invalid={fieldState.invalid}>
                  <FieldLabel htmlFor="signup-password">Password</FieldLabel>
                  <PasswordInput
                    id="signup-password"
                    autoComplete="new-password"
                    placeholder="At least 8 characters"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                  <FieldError errors={[fieldState.error]} />
                </Field>
              )}
            />
            <Controller
              name="confirmPassword"
              control={form.control}
              render={({ field, fieldState }) => (
                <Field data-invalid={fieldState.invalid}>
                  <FieldLabel htmlFor="signup-confirm">Confirm</FieldLabel>
                  <PasswordInput
                    id="signup-confirm"
                    autoComplete="new-password"
                    aria-invalid={fieldState.invalid}
                    {...field}
                  />
                  <FieldError errors={[fieldState.error]} />
                </Field>
              )}
            />
          </div>
          {form.formState.errors.root && (
            <FieldError>{form.formState.errors.root.message}</FieldError>
          )}
          <Button type="submit" className="mt-1 w-full" disabled={pending}>
            {signup.isPending ? 'Creating account...' : 'Create account'}
          </Button>
        </FieldGroup>
      </form>
    </AuthLayout>
  )
}

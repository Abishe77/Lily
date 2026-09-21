import { useState } from "react";
import "./register.css";

/* ─── Icons ─────────────────────────────────────────────────────────── */

function EyeOpen() {
  return (
    <svg
      width="17"
      height="17"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeClosed() {
  return (
    <svg
      width="17"
      height="17"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}

function GoogleMark() {
  return (
    <svg
      width="17"
      height="17"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
      />
    </svg>
  );
}

/* ─── Botanical illustration ───────────────────────────────────────── */

function BotanicalLily() {
  return (
    <svg
      viewBox="0 0 400 500"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      style={{
        width: "100%",
        maxWidth: 300,
        display: "block",
      }}
    >
      {/* Water ripple rings */}
      <ellipse
        cx="200"
        cy="438"
        rx="110"
        ry="20"
        stroke="#A99EC0"
        strokeWidth="0.9"
        opacity="0.28"
      />
      <ellipse
        cx="200"
        cy="438"
        rx="77"
        ry="13"
        stroke="#7FB3B1"
        strokeWidth="0.7"
        opacity="0.24"
      />
      <ellipse
        cx="200"
        cy="438"
        rx="46"
        ry="8"
        stroke="#C4978A"
        strokeWidth="0.6"
        opacity="0.3"
      />
      <ellipse
        cx="200"
        cy="438"
        rx="20"
        ry="4"
        stroke="#A99EC0"
        strokeWidth="0.5"
        opacity="0.2"
      />

      {/* Main stem */}
      <path
        d="M200 428 C199 398 201 358 197 318 C194 288 190 262 196 230 C200 208 204 185 200 155"
        stroke="#7FB3B1"
        strokeWidth="1.4"
        strokeLinecap="round"
        opacity="0.75"
      />

      {/* Lower leaf pair */}
      <path
        d="M198 320 C178 304 152 308 142 328 C162 335 185 326 198 320Z"
        fill="#7FB3B1"
        opacity="0.22"
      />
      <path
        d="M199 320 C219 304 245 310 252 330 C232 336 208 327 199 320Z"
        fill="#7FB3B1"
        opacity="0.18"
      />

      {/* Upper leaf pair */}
      <path
        d="M197 240 C175 224 148 230 138 252 C159 258 182 248 197 240Z"
        fill="#A99EC0"
        opacity="0.2"
      />
      <path
        d="M199 238 C222 222 250 229 258 252 C236 257 212 247 199 238Z"
        fill="#A99EC0"
        opacity="0.16"
      />

      {/* Small side bud */}
      <path
        d="M196 196 C185 182 174 170 178 155 C184 160 192 174 196 196Z"
        fill="#C4978A"
        opacity="0.28"
      />
      <path
        d="M196 196 L180 170"
        stroke="#7FB3B1"
        strokeWidth="0.8"
        opacity="0.5"
        strokeLinecap="round"
      />

      {/* Petals */}
      <path
        d="M200 152 C193 130 182 110 188 84 C195 90 204 112 200 152Z"
        fill="#EDE8F5"
        stroke="#A99EC0"
        strokeWidth="0.8"
        opacity="0.72"
      />
      <path
        d="M200 152 C207 130 218 110 212 84 C205 90 196 112 200 152Z"
        fill="#EDE8F5"
        stroke="#A99EC0"
        strokeWidth="0.8"
        opacity="0.72"
      />
      <path
        d="M200 152 C178 143 158 144 142 156 C150 166 175 159 200 152Z"
        fill="#DAF0EE"
        stroke="#7FB3B1"
        strokeWidth="0.8"
        opacity="0.68"
      />
      <path
        d="M200 152 C222 143 242 144 258 156 C250 166 225 159 200 152Z"
        fill="#DAF0EE"
        stroke="#7FB3B1"
        strokeWidth="0.8"
        opacity="0.68"
      />
      <path
        d="M200 152 C180 162 164 176 162 196 C173 195 190 178 200 152Z"
        fill="#F5E8EC"
        stroke="#C4978A"
        strokeWidth="0.8"
        opacity="0.65"
      />
      <path
        d="M200 152 C220 162 236 176 238 196 C227 195 210 178 200 152Z"
        fill="#F5E8EC"
        stroke="#C4978A"
        strokeWidth="0.8"
        opacity="0.65"
      />

      {/* Stamen */}
      <line
        x1="200"
        y1="150"
        x2="200"
        y2="128"
        stroke="#C4978A"
        strokeWidth="0.7"
        opacity="0.5"
      />
      <line
        x1="200"
        y1="150"
        x2="192"
        y2="130"
        stroke="#C4978A"
        strokeWidth="0.7"
        opacity="0.45"
      />
      <line
        x1="200"
        y1="150"
        x2="208"
        y2="130"
        stroke="#C4978A"
        strokeWidth="0.7"
        opacity="0.45"
      />
      <line
        x1="200"
        y1="150"
        x2="196"
        y2="126"
        stroke="#A99EC0"
        strokeWidth="0.6"
        opacity="0.4"
      />
      <line
        x1="200"
        y1="150"
        x2="204"
        y2="126"
        stroke="#A99EC0"
        strokeWidth="0.6"
        opacity="0.4"
      />

      {/* Anthers */}
      <circle cx="200" cy="127" r="2.2" fill="#C4978A" opacity="0.6" />
      <circle cx="192" cy="129" r="1.8" fill="#C4978A" opacity="0.55" />
      <circle cx="208" cy="129" r="1.8" fill="#C4978A" opacity="0.55" />
      <circle cx="196" cy="125" r="1.5" fill="#A99EC0" opacity="0.5" />
      <circle cx="204" cy="125" r="1.5" fill="#A99EC0" opacity="0.5" />

      {/* Flower center */}
      <circle cx="200" cy="152" r="7" fill="#E8D8E0" opacity="0.6" />
      <circle cx="200" cy="152" r="3.5" fill="#C4978A" opacity="0.4" />

      {/* Floating fragments */}
      <ellipse
        cx="130"
        cy="350"
        rx="14"
        ry="5"
        fill="#C4978A"
        opacity="0.09"
        transform="rotate(-40 130 350)"
      />
      <ellipse
        cx="272"
        cy="370"
        rx="10"
        ry="4"
        fill="#A99EC0"
        opacity="0.1"
        transform="rotate(25 272 370)"
      />
      <ellipse
        cx="118"
        cy="270"
        rx="8"
        ry="3"
        fill="#7FB3B1"
        opacity="0.1"
        transform="rotate(-20 118 270)"
      />
      <ellipse
        cx="284"
        cy="290"
        rx="6"
        ry="2.5"
        fill="#C4978A"
        opacity="0.09"
        transform="rotate(35 284 290)"
      />
      <ellipse
        cx="150"
        cy="180"
        rx="5"
        ry="2"
        fill="#A99EC0"
        opacity="0.12"
        transform="rotate(-50 150 180)"
      />
    </svg>
  );
}

/* ─── Form field ───────────────────────────────────────────────────── */

function Field({
  id,
  label,
  type = "text",
  placeholder,
  value,
  onChange,
  password = false,
}) {
  const [show, setShow] = useState(false);
  const inputType = password ? (show ? "text" : "password") : type;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 5,
      }}
    >
      <label
        htmlFor={id}
        style={{
          fontSize: 11.5,
          fontWeight: 500,
          color: "var(--mid)",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
        }}
      >
        {label}
      </label>

      <div style={{ position: "relative" }}>
        <input
          id={id}
          type={inputType}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="lily-field"
          style={{
            paddingRight: password ? 46 : 16,
          }}
          autoComplete={
            password
              ? "new-password"
              : id === "email"
              ? "email"
              : "name"
          }
        />

        {password && (
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            aria-label={show ? "Hide password" : "Show password"}
            style={{
              position: "absolute",
              right: 14,
              top: "50%",
              transform: "translateY(-50%)",
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "var(--muted)",
              padding: 2,
              display: "flex",
              alignItems: "center",
              transition: "color 0.15s",
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.color = "var(--ink)")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.color = "var(--muted)")
            }
          >
            {show ? <EyeOpen /> : <EyeClosed />}
          </button>
        )}
      </div>
    </div>
  );
}

/* ─── Main component ───────────────────────────────────────────────── */

export default function App() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [pass, setPass] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();

    if (pass !== confirm) {
      setMessage("Passwords do not match");
      return;
    }

    try {
      const response = await fetch(
        "http://127.0.0.1:8000/register",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: name,
            email: email,
            password: pass,
          }),
        }
      );

      const data = await response.json();

      if (response.ok) {
        setMessage(data.message);
      } else {
        setMessage("Registration failed");
      }
    } catch (error) {
      console.error(error);
      setMessage("Could not connect to Lily backend");
    }
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1.05fr 0.95fr",
        width: "100%",
        height: "100vh",
        minHeight: 0,
        overflow: "hidden",
      }}
    >
      {/* ══════════════ LEFT PANEL ══════════════ */}

      <div
        style={{
          background:
            "linear-gradient(148deg, #EAE3D8 0%, #E3DCED 52%, #D4E8E6 100%)",
          position: "relative",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "30px 56px",
          minHeight: 0,
        }}
      >
        {/* Ambient orbs */}

        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            top: "-10%",
            right: "-5%",
            width: 320,
            height: 320,
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(169,158,192,0.2) 0%, transparent 65%)",
            pointerEvents: "none",
          }}
        />

        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            bottom: "5%",
            left: "-8%",
            width: 260,
            height: 260,
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(127,179,177,0.16) 0%, transparent 65%)",
            pointerEvents: "none",
          }}
        />

        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            top: "40%",
            left: "50%",
            width: 180,
            height: 180,
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(196,151,138,0.1) 0%, transparent 65%)",
            pointerEvents: "none",
          }}
        />

        {/* Wordmark */}

        <div
          style={{
            position: "relative",
            zIndex: 1,
          }}
        >
          <div
            style={{
              fontFamily: "'Playfair Display', Georgia, serif",
              fontSize: "clamp(52px, 6vw, 72px)",
              fontWeight: 400,
              fontStyle: "italic",
              color: "var(--charcoal)",
              letterSpacing: "-0.03em",
              lineHeight: 1,
              marginBottom: 12,
            }}
          >
            Lily
          </div>

          <p
            style={{
              fontFamily: "'Playfair Display', Georgia, serif",
              fontSize: "clamp(13px, 1.15vw, 15px)",
              fontWeight: 400,
              fontStyle: "italic",
              color: "var(--mid)",
              margin: 0,
              lineHeight: 1.5,
            }}
          >
            Your personal learning companion.
          </p>
        </div>

        {/* Illustration */}

        <div
          style={{
            position: "relative",
            zIndex: 1,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            margin: "0 auto",
            width: "100%",
            maxWidth: 300,
            flex: 1,
            minHeight: 0,
            padding: "10px 0",
          }}
        >
          <BotanicalLily />
        </div>

        {/* Supporting copy */}

        <div
          style={{
            position: "relative",
            zIndex: 1,
          }}
        >
          <div
            style={{
              width: 32,
              height: 1,
              background:
                "linear-gradient(90deg, var(--rose), var(--lavender))",
              marginBottom: 12,
              opacity: 0.6,
            }}
          />

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 2,
            }}
          >
            {[
              "Learn at your pace.",
              "Revise your way.",
              "Grow with Lily.",
            ].map((line, i) => (
              <p
                key={i}
                style={{
                  fontFamily:
                    "'Playfair Display', Georgia, serif",
                  fontSize: "clamp(12px, 1vw, 14px)",
                  fontWeight: 400,
                  fontStyle: "italic",
                  color:
                    i === 2
                      ? "var(--ink)"
                      : "var(--mid)",
                  margin: 0,
                  lineHeight: 1.5,
                  opacity: i === 2 ? 0.85 : 0.7,
                }}
              >
                {line}
              </p>
            ))}
          </div>
        </div>
      </div>

      {/* ══════════════ RIGHT PANEL ══════════════ */}

      <div
        style={{
          background: "var(--bg)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "16px 40px",
          minHeight: 0,
          overflowY: "auto",
        }}
      >
        <div
          style={{
            width: "100%",
            maxWidth: 400,
          }}
        >
          {/* Lily monogram */}

          <div
            style={{
              marginBottom: 20,
            }}
          >
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 34,
                height: 34,
                borderRadius: "50%",
                background:
                  "linear-gradient(135deg, #EDE8F5, #DAF0EE)",
                marginBottom: 16,
                boxShadow:
                  "0 2px 12px rgba(169,158,192,0.2)",
              }}
            >
              <span
                style={{
                  fontFamily:
                    "'Playfair Display', Georgia, serif",
                  fontSize: 16,
                  fontStyle: "italic",
                  color: "var(--lavender)",
                  lineHeight: 1,
                  userSelect: "none",
                }}
              >
                L
              </span>
            </div>

            <h1
              style={{
                fontFamily:
                  "'Playfair Display', Georgia, serif",
                fontSize: "clamp(22px, 2.2vw, 28px)",
                fontWeight: 400,
                fontStyle: "italic",
                color: "var(--charcoal)",
                letterSpacing: "-0.015em",
                lineHeight: 1.2,
                margin: "0 0 7px",
              }}
            >
              Create your Lily account
            </h1>

            <p
              style={{
                fontSize: 13,
                fontWeight: 300,
                color: "var(--muted)",
                margin: 0,
                lineHeight: 1.5,
              }}
            >
              Let's create a learning space that feels like yours.
            </p>
          </div>

          {/* Form */}

          <form
            onSubmit={handleSubmit}
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 11,
            }}
          >
            <Field
              id="name"
              label="Full Name"
              placeholder="Enter your name"
              value={name}
              onChange={setName}
            />

            <Field
              id="email"
              label="Email"
              placeholder="Enter your email"
              value={email}
              onChange={setEmail}
              type="email"
            />

            <Field
              id="password"
              label="Password"
              placeholder="Create a password"
              value={pass}
              onChange={setPass}
              password
            />

            <Field
              id="confirm"
              label="Confirm Password"
              placeholder="Confirm your password"
              value={confirm}
              onChange={setConfirm}
              password
            />

            {/* CTA */}

            <div
              style={{
                marginTop: 2,
              }}
            >
              <button
                type="submit"
                className="btn-primary"
              >
                Create Account
              </button>
            </div>

            {message && (
              <p
                style={{
                  textAlign: "center",
                  fontSize: 12,
                  color: "var(--muted)",
                  margin: 0,
                }}
              >
                {message}
              </p>
            )}

            {/* Divider */}

            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              <div
                style={{
                  flex: 1,
                  height: 1,
                  background: "var(--border-soft)",
                }}
              />

              <span
                style={{
                  fontSize: 10,
                  fontWeight: 500,
                  color: "var(--faint)",
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                }}
              >
                or
              </span>

              <div
                style={{
                  flex: 1,
                  height: 1,
                  background: "var(--border-soft)",
                }}
              />
            </div>

            {/* Google */}

            <button
              type="button"
              className="btn-google"
            >
              <GoogleMark />
              Continue with Google
            </button>
          </form>

          {/* Login */}

          <p
            style={{
              marginTop: 18,
              marginBottom: 0,
              textAlign: "center",
              fontSize: 12,
              fontWeight: 300,
              color: "var(--muted)",
              lineHeight: 1.5,
            }}
          >
            Already have an account?{" "}
            <LogInLink />
          </p>

          {/* Legal */}

          <p
            style={{
              marginTop: 10,
              marginBottom: 0,
              textAlign: "center",
              fontSize: 10.5,
              fontWeight: 300,
              color: "var(--faint)",
              lineHeight: 1.5,
            }}
          >
            By continuing, you agree to Lily's{" "}
            <a
              href="#"
              style={{
                color: "var(--muted)",
                textDecoration: "underline",
                textDecorationColor: "var(--border)",
              }}
            >
              Terms
            </a>
            {" & "}
            <a
              href="#"
              style={{
                color: "var(--muted)",
                textDecoration: "underline",
                textDecorationColor: "var(--border)",
              }}
            >
              Privacy Policy
            </a>
            .
          </p>
        </div>
      </div>
    </div>
  );
}

/* ─── Login link ───────────────────────────────────────────────────── */

function LogInLink() {
  const [hovered, setHovered] = useState(false);

  return (
    <a
      href="#"
      style={{
        color: hovered
          ? "var(--lavender)"
          : "var(--ink)",
        fontWeight: 500,
        textDecoration: "none",
        borderBottom: `1px solid ${
          hovered
            ? "var(--lavender)"
            : "var(--border)"
        }`,
        paddingBottom: 1,
        transition:
          "color 0.2s, border-color 0.2s",
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      Log in
    </a>
  );
}





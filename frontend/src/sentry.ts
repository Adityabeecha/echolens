// The only parts of the Sentry SDK EchoLens uses. Importing the package as a
// namespace pulled every integration (session replay, feedback widget…) into
// the chunk; named exports let the bundler drop the rest.
export { captureException, init } from "@sentry/browser";

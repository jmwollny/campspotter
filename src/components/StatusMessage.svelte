<!-- The latest progress or error message; announced to screen readers as it changes. -->
<script lang="ts">
  import { status } from "../lib/stores";
</script>

<p class="status" class:error-text={$status.isError} role="status" aria-live="polite">
  {$status.message}
</p>

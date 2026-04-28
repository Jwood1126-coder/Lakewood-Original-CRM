# Embedding the "Request a Quote" form on lakewoodoriginal.com

The CRM exposes a public endpoint at:

```
POST https://<your-railway-domain>/intake/api/request
```

This snippet is a self-contained `<form>` you can paste into a **WordPress
Custom HTML block** (Add Block → Custom HTML). It POSTs the user's input
as JSON to the CRM, which:

1. Creates a Client (or matches an existing one by phone+name)
2. Creates a Property at the given address with auto Ohio tax-rate from ZIP
3. Creates a Quote in `draft` status
4. Pings you (in-app inbox + email if you've enabled the event)

The form is responsive, matches your site's dark aesthetic, and includes a
hidden honeypot field to defeat basic spambots.

**Before pasting, replace `YOUR-CRM-DOMAIN.up.railway.app` with the real Railway domain (or your custom domain when you set one up).**

```html
<style>
  .lo-intake { max-width: 32rem; margin: 0 auto; font-family: system-ui, -apple-system, sans-serif; color: #e4ecf0; }
  .lo-intake label { display: block; font-size: 0.85rem; color: #97a5ad; margin: 0.7rem 0 0.2rem; }
  .lo-intake input, .lo-intake select, .lo-intake textarea {
    width: 100%; padding: 0.7rem; font-size: 16px; box-sizing: border-box;
    background: #1b2429; color: #e4ecf0; border: 1px solid #2c3a42; border-radius: 6px;
  }
  .lo-intake textarea { resize: vertical; min-height: 90px; }
  .lo-intake .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }
  .lo-intake button {
    width: 100%; margin-top: 1.2rem; padding: 0.9rem; font-size: 1rem; font-weight: 600;
    background: #f59e0b; color: #1a1407; border: none; border-radius: 8px; cursor: pointer;
  }
  .lo-intake button:disabled { opacity: 0.6; cursor: wait; }
  .lo-intake-hp { position: absolute !important; left: -9999px !important; top: -9999px !important; }
  .lo-intake-msg { padding: 0.8rem 1rem; border-radius: 8px; margin-top: 1rem; }
  .lo-intake-msg.ok { background: #14532d; color: #bbf7d0; }
  .lo-intake-msg.err { background: #7f1d1d; color: #fecaca; }
</style>

<form class="lo-intake" id="lo-intake-form" novalidate>
  <input type="text" name="website" class="lo-intake-hp" tabindex="-1" autocomplete="off" aria-hidden="true">

  <label for="lo-name">Your name *</label>
  <input id="lo-name" name="name" required>

  <div class="row">
    <div>
      <label for="lo-phone">Phone</label>
      <input id="lo-phone" name="phone" type="tel" inputmode="tel">
    </div>
    <div>
      <label for="lo-email">Email</label>
      <input id="lo-email" name="email" type="email">
    </div>
  </div>

  <label for="lo-service">What do you need?</label>
  <select id="lo-service" name="service">
    <option value="woodworking">Woodworking & Carpentry</option>
    <option value="doors_hardware">Doors, Hardware & Fixtures</option>
    <option value="kitchen_bath">Kitchen & Bath Updates</option>
    <option value="assembly">Assembly Services</option>
    <option value="installation">Installation & Mounting</option>
    <option value="other">Something else</option>
  </select>

  <label for="lo-description">Project description *</label>
  <textarea id="lo-description" name="description" required
    placeholder="What needs doing? Photos help — text them after."></textarea>

  <label for="lo-address">Address</label>
  <input id="lo-address" name="address" autocomplete="address-line1">

  <div class="row">
    <div>
      <label for="lo-city">City</label>
      <select id="lo-city" name="city">
        <option value="">— pick —</option>
        <option>Lakewood</option>
        <option>Rocky River</option>
        <option>Westlake</option>
        <option>Cleveland</option>
        <option>Parma</option>
        <option>Parma Heights</option>
        <option>Avon</option>
        <option>Berea</option>
        <option>North Royalton</option>
        <option>Strongsville</option>
        <option>Broadview Heights</option>
        <option>Brecksville</option>
        <option>Olmsted Falls</option>
        <option value="other">Other</option>
      </select>
    </div>
    <div>
      <label for="lo-zip">ZIP</label>
      <input id="lo-zip" name="zip" inputmode="numeric" maxlength="10">
    </div>
  </div>

  <button type="submit" id="lo-submit">Send request</button>
  <div id="lo-msg"></div>
</form>

<script>
(function() {
  // ⚠️ REPLACE THIS with your real Railway domain (or custom domain).
  var CRM_URL = "https://YOUR-CRM-DOMAIN.up.railway.app/intake/api/request";

  var form = document.getElementById("lo-intake-form");
  var btn = document.getElementById("lo-submit");
  var msg = document.getElementById("lo-msg");

  form.addEventListener("submit", function(e) {
    e.preventDefault();
    msg.className = ""; msg.textContent = "";

    var data = {};
    new FormData(form).forEach(function(v, k) { data[k] = v; });

    if (!data.name || (!data.phone && !data.email) || !data.description) {
      msg.className = "lo-intake-msg err";
      msg.textContent = "Please fill in your name, phone or email, and project description.";
      return;
    }

    btn.disabled = true; btn.textContent = "Sending…";

    fetch(CRM_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
    .then(function(r) { return r.json().then(function(j) { return { ok: r.ok, body: j }; }); })
    .then(function(res) {
      if (res.ok) {
        msg.className = "lo-intake-msg ok";
        msg.textContent = res.body.message || "Thanks — we'll be in touch within one business day.";
        form.reset();
      } else {
        msg.className = "lo-intake-msg err";
        msg.textContent = res.body.error || "Something went wrong. Please call (216) 770-7034.";
      }
    })
    .catch(function() {
      msg.className = "lo-intake-msg err";
      msg.textContent = "Could not reach the server. Please call (216) 770-7034.";
    })
    .finally(function() { btn.disabled = false; btn.textContent = "Send request"; });
  });
})();
</script>
```

## Setup steps in WordPress

1. Edit the page where the existing "Contact" / "Inquiry" section lives.
2. Delete the old form block (or hide it).
3. **Add Block → Custom HTML**. Paste the snippet above.
4. **Edit the snippet** — change `YOUR-CRM-DOMAIN.up.railway.app` to your real Railway domain.
5. Update the page. Test by submitting the form yourself.

## What you'll see when it works

- The submitter sees a green "Thanks — we'll be in touch" message.
- You get a notification in your CRM **Inbox** ("📩 New request from [name]").
- You get an email (if SMTP is set up + the toggle is on in Settings → Notifications).
- A new **draft Quote** appears in your CRM, pre-populated with the customer's
  description in the internal notes. You build out line items and send it.
- The Today dashboard surfaces a "📩 New website requests" tile until you
  move the quote out of `draft`.

## If the website is on Wix / Squarespace / something else

Same JSON endpoint works. Use whatever Custom Code block your platform
provides; the JS makes a plain `fetch()` POST.

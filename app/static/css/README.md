# Static CSS

`app.css` is our small set of overrides on top of [Pico.css](https://picocss.com/).

Pico itself is loaded from the jsDelivr CDN in `templates/base.html`. If you'd
prefer to vendor it (zero network deps at runtime), download
`pico.classless.min.css` from
https://github.com/picocss/pico/releases and drop it next to this README, then
swap the `<link>` tag in `base.html` to `{{ url_for('static', filename='css/pico.classless.min.css') }}`.

For dev: the CDN is fine. For production durability: vendor it.

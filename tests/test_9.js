console.log("Hello! This is printing from inside JavaScript!");

var allow_submit = true
var strong = document.querySelectorAll("strong")[0]

function checkLength() {
  var value = this.getAttribute("value");
  allow_submit = value.length <= 100;
  if (!allow_submit) {
    strong.innerHTML = 'Comment too long!';
  } else {
    strong.innerHTML = "";
  }
}

var inputs = document.querySelectorAll("input");
for (var i = 0; i < inputs.length; i++) {
 inputs[i].addEventListener("keydown", checkLength);
}

var forms = document.querySelectorAll("form")
if (forms.length > 0) {
  var form = forms[0];
  form.addEventListener("submit", function(e) {
    if (!allow_submit) e.preventDefault();
  })
}
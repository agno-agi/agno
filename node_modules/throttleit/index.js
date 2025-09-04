function throttle(function_, wait) {
	if (typeof function_ !== 'function') {
		throw new TypeError(`Expected the first argument to be a \`function\`, got \`${typeof function_}\`.`);
	}

	// TODO: Add `wait` validation too in the next major version.

	let timeoutId;
	let lastCallTime = 0;

	return function throttled(...arguments_) { // eslint-disable-line func-names
		clearTimeout(timeoutId);

		const now = Date.now();
		const timeSinceLastCall = now - lastCallTime;
		const delayForNextCall = wait - timeSinceLastCall;

		if (delayForNextCall <= 0) {
			lastCallTime = now;
			function_.apply(this, arguments_);
		} else {
			timeoutId = setTimeout(() => {
				lastCallTime = Date.now();
				function_.apply(this, arguments_);
			}, delayForNextCall);
		}
	};
}

module.exports = throttle;
